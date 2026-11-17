import logging

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.models import PullRequest, Review
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reviews"])


@router.get("/reviews/{review_id}")
async def get_review(
    review_id: int,
    session: AsyncSession = Depends(get_db),
) -> dict:
    result = await session.execute(
        select(Review).where(Review.id == review_id).options(selectinload(Review.comments))
    )
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found",
        )

    return {
        "id": review.id,
        "pull_request_id": review.pull_request_id,
        "status": review.status,
        "summary": review.summary,
        "model": review.model,
        "input_tokens": review.input_tokens,
        "output_tokens": review.output_tokens,
        "error": review.error,
        "created_at": review.created_at.isoformat() if review.created_at else None,
        "finished_at": review.finished_at.isoformat() if review.finished_at else None,
        "comments": [
            {
                "id": c.id,
                "file_path": c.file_path,
                "line": c.line,
                "severity": c.severity,
                "body": c.body,
            }
            for c in review.comments
        ],
    }


@router.post("/reviews/{review_id}/retry")
async def retry_review(
    review_id: int,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Re-queue a failed review. Only failed reviews can be retried."""
    result = await session.execute(
        select(Review)
        .where(Review.id == review_id)
        .options(selectinload(Review.pull_request).selectinload(PullRequest.repository))
    )
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Review {review_id} not found",
        )

    if review.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only failed reviews can be retried (current: {review.status})",
        )

    pr = review.pull_request
    repo = pr.repository

    review.status = "queued"
    review.error = None
    review.finished_at = None
    # Commit before enqueueing so the worker never sees the stale 'failed' state.
    await session.commit()

    settings = get_settings()
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    pool = await create_pool(redis_settings)
    try:
        # review_id makes the worker reuse this row instead of creating a new review.
        await pool.enqueue_job(
            "run_review",
            repo.github_repo_id,
            repo.full_name,
            pr.number,
            pr.head_sha,
            pr.title or "",
            review_id=review.id,
        )
    finally:
        await pool.aclose()

    logger.info("Re-queued review %s for %s#%s", review.id, repo.full_name, pr.number)
    return {"status": "queued", "review_id": review.id}
