import json
import logging
from typing import Annotated, Any

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Header, HTTPException, status
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.security import require_github_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SUPPORTED_ACTIONS = {"opened", "synchronize", "reopened"}


def _parse_pr_event(payload: dict[str, Any]) -> tuple[int, str, int, str, str] | None:
    """Extract repo_id, full_name, pr_number, head_sha, title from pull_request event."""
    if payload.get("action") not in SUPPORTED_ACTIONS:
        return None

    pr = payload.get("pull_request") or {}
    repo = payload.get("repository") or {}
    head = pr.get("head") or {}

    github_repo_id = repo.get("id")
    full_name = repo.get("full_name")
    number = pr.get("number")
    head_sha = head.get("sha")
    title = pr.get("title") or ""

    if github_repo_id is None or number is None or not full_name or not head_sha:
        return None

    return int(github_repo_id), str(full_name), int(number), str(head_sha), str(title)


@router.post("/github")
async def github_webhook(
    body: Annotated[bytes, Depends(require_github_signature)],
    x_github_event: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """Receive GitHub pull_request webhook, dedupe, and enqueue review job."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    if x_github_event == "ping" or payload.get("zen"):
        return {"status": "pong"}
    if x_github_event is not None and x_github_event != "pull_request":
        return {"status": "ignored"}

    parsed = _parse_pr_event(payload)
    if parsed is None:
        return {"status": "ignored"}

    github_repo_id, full_name, pr_number, head_sha, title = parsed
    settings = get_settings()

    # Idempotency: same repo + PR + commit → process once
    key = f"review:{github_repo_id}:{pr_number}:{head_sha}"
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        was_set = await redis.set(key, "1", nx=True, ex=3600)
        if not was_set:
            logger.info("Duplicate webhook ignored: %s", key)
            return {"status": "duplicate_ignored"}

        # Enqueue arq job (worker will pick it up later)
        try:
            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            try:
                await pool.enqueue_job(
                    "run_review",
                    github_repo_id,
                    full_name,
                    pr_number,
                    head_sha,
                    title,
                )
            finally:
                await pool.aclose()
        except Exception:
            # Release the idempotency key so GitHub's redelivery is not dropped as duplicate.
            await redis.delete(key)
            logger.exception("Enqueue failed, idempotency key released: %s", key)
            raise
    finally:
        await redis.aclose()

    logger.info("Enqueued review job: repo=%s pr=%s sha=%s", full_name, pr_number, head_sha[:7])
    return {"status": "queued"}
