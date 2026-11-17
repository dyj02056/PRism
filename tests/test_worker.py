from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from arq import Retry

from app.services.llm_reviewer import ReviewCommentOut, ReviewResult
from app.worker.tasks import MAX_TRIES, _get_or_create_review, _post_to_github, run_review


def _session_factory(mock_session):
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = mock_session
    session_cm.__aexit__.return_value = None
    return MagicMock(return_value=session_cm)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_review():
    return MagicMock(id=100, status="queued", error=None)


def _patches(mock_session, mock_review, github, llm):
    return (
        patch("app.worker.tasks.AsyncSessionLocal", _session_factory(mock_session)),
        patch("app.worker.tasks._get_or_create_repo", AsyncMock(return_value=MagicMock(id=1))),
        patch("app.worker.tasks._get_or_create_pr", AsyncMock(return_value=MagicMock(id=10))),
        patch("app.worker.tasks._get_or_create_review", AsyncMock(return_value=mock_review)),
        patch("app.worker.tasks.get_github_client", return_value=github),
        patch("app.worker.tasks.get_llm_reviewer", return_value=llm),
    )


async def test_run_review_success_path(mock_session, mock_review):
    """Worker marks review done, stores comments and posts to GitHub."""
    mock_session.get = AsyncMock(return_value=mock_review)
    llm_result = ReviewResult(
        summary="Looks good",
        comments=[ReviewCommentOut(file_path="a.py", line=3, severity="info", body="nit")],
        model="mock",
        input_tokens=10,
        output_tokens=5,
    )
    github = AsyncMock()
    github.get_pull_diff = AsyncMock(return_value="diff --git a/a.py b/a.py")
    llm = AsyncMock()
    llm.review = AsyncMock(return_value=llm_result)

    p = _patches(mock_session, mock_review, github, llm)
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        result = await run_review({"job_try": 1}, 99, "acme/demo", 1, "abc", "feat")

    assert result == {"review_id": 100, "status": "done", "comments": 1}
    assert mock_review.status == "done"
    assert mock_review.input_tokens == 10
    github.create_pull_review.assert_awaited_once()
    mock_session.add.assert_called_once()  # one ReviewComment row


async def test_run_review_transient_failure_raises_retry(mock_session, mock_review):
    """Before the last try: review goes back to queued and arq Retry is raised."""
    mock_session.get = AsyncMock(return_value=mock_review)
    github = AsyncMock()
    github.get_pull_diff = AsyncMock(side_effect=RuntimeError("github down"))

    p = _patches(mock_session, mock_review, github, AsyncMock())
    with p[0], p[1], p[2], p[3], p[4], p[5], pytest.raises(Retry):
        await run_review({"job_try": 1}, 99, "acme/demo", 1, "abc", "feat")

    assert mock_review.status == "queued"
    assert "github down" in mock_review.error


async def test_run_review_final_failure_marks_failed(mock_session, mock_review):
    """On the last try: review is marked failed with the error recorded."""
    mock_session.get = AsyncMock(return_value=mock_review)
    github = AsyncMock()
    github.get_pull_diff = AsyncMock(side_effect=RuntimeError("github down"))

    p = _patches(mock_session, mock_review, github, AsyncMock())
    with p[0], p[1], p[2], p[3], p[4], p[5]:
        result = await run_review({"job_try": MAX_TRIES}, 99, "acme/demo", 1, "abc", "feat")

    assert result["status"] == "failed"
    assert mock_review.status == "failed"
    assert "github down" in mock_review.error
    assert mock_review.finished_at is not None


async def test_get_or_create_review_reuses_given_id(mock_session, mock_review):
    """Manual retry passes review_id: the existing row is reused, nothing is added."""
    mock_session.get = AsyncMock(return_value=mock_review)

    review = await _get_or_create_review(mock_session, MagicMock(id=10), review_id=100)

    assert review is mock_review
    mock_session.add.assert_not_called()


async def test_get_or_create_review_reuses_unfinished(mock_session, mock_review):
    """Automatic arq retry (no review_id) finds the queued review of the same PR."""
    exec_result = MagicMock()
    exec_result.scalar_one_or_none.return_value = mock_review
    mock_session.execute = AsyncMock(return_value=exec_result)

    review = await _get_or_create_review(mock_session, MagicMock(id=10), review_id=None)

    assert review is mock_review
    mock_session.add.assert_not_called()


async def test_post_to_github_falls_back_to_issue_comment():
    """If GitHub rejects line comments (e.g. 422), a summary issue comment is posted."""
    github = AsyncMock()
    github.create_pull_review = AsyncMock(side_effect=RuntimeError("422"))
    comments = [ReviewCommentOut(file_path="a.py", line=999, severity="warning", body="x")]

    await _post_to_github(github, "acme/demo", 1, "summary", comments)

    github.create_issue_comment.assert_awaited_once()
    body = github.create_issue_comment.await_args.args[2]
    assert "a.py:999" in body
