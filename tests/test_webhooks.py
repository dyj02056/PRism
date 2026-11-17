import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
SECRET = "test-webhook-secret"


def _sign(body: bytes, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
def client(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture
def pr_payload() -> bytes:
    data = (FIXTURES / "pr_opened.json").read_bytes()
    return data


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_webhook_missing_signature(client, pr_payload):
    resp = client.post("/webhooks/github", content=pr_payload)
    assert resp.status_code == 401


def test_webhook_invalid_signature(client, pr_payload):
    resp = client.post(
        "/webhooks/github",
        content=pr_payload,
        headers={"X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert resp.status_code == 401


def test_webhook_valid_and_enqueue(client, pr_payload):
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)  # NX success
    mock_redis.aclose = AsyncMock()

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock()
    mock_pool.aclose = AsyncMock()

    with (
        patch("app.api.webhooks.Redis.from_url", return_value=mock_redis),
        patch("app.api.webhooks.create_pool", AsyncMock(return_value=mock_pool)),
    ):
        resp = client.post(
            "/webhooks/github",
            content=pr_payload,
            headers={"X-Hub-Signature-256": _sign(pr_payload)},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "queued"}
    mock_redis.set.assert_awaited_once()
    call_args = mock_redis.set.await_args
    assert call_args.args[0].startswith("review:123456789:42:")
    assert call_args.kwargs.get("nx") is True
    mock_pool.enqueue_job.assert_awaited_once()
    job_args = mock_pool.enqueue_job.await_args
    assert job_args.args[0] == "run_review"
    assert job_args.args[1] == 123456789  # github_repo_id
    assert job_args.args[3] == 42  # pr number


def test_webhook_duplicate_ignored(client, pr_payload):
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=False)  # already exists
    mock_redis.aclose = AsyncMock()

    with patch("app.api.webhooks.Redis.from_url", return_value=mock_redis):
        resp = client.post(
            "/webhooks/github",
            content=pr_payload,
            headers={"X-Hub-Signature-256": _sign(pr_payload)},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "duplicate_ignored"}
    mock_redis.set.assert_awaited_once()


def test_webhook_ignored_action(client):
    payload = {
        "action": "closed",
        "pull_request": {"number": 1, "head": {"sha": "abc"}, "title": "x"},
        "repository": {"id": 1, "full_name": "a/b"},
    }
    body = json.dumps(payload).encode()
    mock_redis = AsyncMock()

    with patch("app.api.webhooks.Redis.from_url", return_value=mock_redis):
        resp = client.post(
            "/webhooks/github",
            content=body,
            headers={"X-Hub-Signature-256": _sign(body)},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}
    mock_redis.set.assert_not_called()


def test_webhook_enqueue_failure_releases_key(client, pr_payload):
    """If enqueue fails, the idempotency key is deleted so a redelivery is not dropped."""
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)

    with (
        patch("app.api.webhooks.Redis.from_url", return_value=mock_redis),
        patch("app.api.webhooks.create_pool", AsyncMock(side_effect=ConnectionError("down"))),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        resp = c.post(
            "/webhooks/github",
            content=pr_payload,
            headers={"X-Hub-Signature-256": _sign(pr_payload)},
        )

    assert resp.status_code == 500
    key = mock_redis.set.await_args.args[0]
    mock_redis.delete.assert_awaited_once_with(key)


def test_webhook_non_pr_event_ignored(client, pr_payload):
    mock_redis = AsyncMock()
    with patch("app.api.webhooks.Redis.from_url", return_value=mock_redis):
        resp = client.post(
            "/webhooks/github",
            content=pr_payload,
            headers={"X-Hub-Signature-256": _sign(pr_payload), "X-GitHub-Event": "push"},
        )

    assert resp.json() == {"status": "ignored"}
    mock_redis.set.assert_not_called()


def test_webhook_ping(client):
    body = json.dumps({"zen": "Keep it logically awesome."}).encode()
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body)},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "pong"}
