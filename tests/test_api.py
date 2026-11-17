from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _session_dep(mock_session):
    async def _get_db():
        yield mock_session

    return _get_db


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    return session


def test_list_repositories(mock_session):
    repo = MagicMock()
    repo.id = 1
    repo.github_repo_id = 123
    repo.full_name = "acme/demo"
    repo.created_at = datetime.now(UTC)

    result = MagicMock()
    result.scalars.return_value.all.return_value = [repo]
    mock_session.execute = AsyncMock(return_value=result)

    from app.db.session import get_db
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_db] = _session_dep(mock_session)
    try:
        with TestClient(fastapi_app) as client:
            resp = client.get("/repositories")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["full_name"] == "acme/demo"
    finally:
        fastapi_app.dependency_overrides.clear()


def test_get_review_with_comments(mock_session):
    comment = MagicMock()
    comment.id = 1
    comment.file_path = "a.py"
    comment.line = 10
    comment.severity = "warning"
    comment.body = "check this"

    review = MagicMock()
    review.id = 5
    review.pull_request_id = 2
    review.status = "done"
    review.summary = "ok"
    review.model = "mock"
    review.input_tokens = 1
    review.output_tokens = 2
    review.error = None
    review.created_at = datetime.now(UTC)
    review.finished_at = datetime.now(UTC)
    review.comments = [comment]

    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = review
    mock_session.execute = AsyncMock(return_value=exec_result)

    from app.db.session import get_db
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_db] = _session_dep(mock_session)
    try:
        with TestClient(fastapi_app) as client:
            resp = client.get("/reviews/5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "done"
        assert len(data["comments"]) == 1
        assert data["comments"][0]["severity"] == "warning"
    finally:
        fastapi_app.dependency_overrides.clear()


def test_stats_summary(mock_session):
    # Three execute calls: repo stats, severity, status
    repo_row = MagicMock()
    repo_row.id = 1
    repo_row.full_name = "acme/demo"
    repo_row.review_count = 3
    repo_row.input_tokens = 100
    repo_row.output_tokens = 50

    sev_row = MagicMock()
    sev_row.severity = "info"
    sev_row.cnt = 2

    status_row = MagicMock()
    status_row.status = "done"
    status_row.cnt = 3

    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(all=MagicMock(return_value=[repo_row])),
            MagicMock(all=MagicMock(return_value=[sev_row])),
            MagicMock(all=MagicMock(return_value=[status_row])),
        ]
    )

    from app.db.session import get_db
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_db] = _session_dep(mock_session)
    try:
        with TestClient(fastapi_app) as client:
            resp = client.get("/stats/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_reviews"] == 3
        assert data["severity_distribution"]["info"] == 2
        assert data["status_distribution"]["done"] == 3
        assert data["by_repository"][0]["full_name"] == "acme/demo"
    finally:
        fastapi_app.dependency_overrides.clear()


def test_retry_failed_reuses_review(mock_session):
    repo = MagicMock(github_repo_id=99, full_name="acme/demo")
    pr = MagicMock(number=4, head_sha="abc", title="feat", repository=repo)
    review = MagicMock(id=7, status="failed", pull_request=pr)
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = review
    mock_session.execute = AsyncMock(return_value=exec_result)

    pool = AsyncMock()

    from app.db.session import get_db
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_db] = _session_dep(mock_session)
    try:
        with (
            patch("app.api.reviews.create_pool", AsyncMock(return_value=pool)),
            TestClient(fastapi_app) as client,
        ):
            resp = client.post("/reviews/7/retry")
        assert resp.status_code == 200
        assert resp.json() == {"status": "queued", "review_id": 7}
        assert review.status == "queued"
        mock_session.commit.assert_awaited()
        # the worker must reuse this row, not create a new review
        assert pool.enqueue_job.await_args.kwargs["review_id"] == 7
    finally:
        fastapi_app.dependency_overrides.clear()


def test_retry_only_failed(mock_session):
    review = MagicMock()
    review.id = 7
    review.status = "done"
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = review
    mock_session.execute = AsyncMock(return_value=exec_result)

    from app.db.session import get_db
    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_db] = _session_dep(mock_session)
    try:
        with TestClient(fastapi_app) as client:
            resp = client.post("/reviews/7/retry")
        assert resp.status_code == 409
    finally:
        fastapi_app.dependency_overrides.clear()
