from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PullRequest, Repository, Review, ReviewComment
from app.db.session import get_db

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/summary")
async def stats_summary(session: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Aggregate review counts, severity distribution, and token usage per repository."""

    # Per-repo review counts + token sums
    repo_stats_q = (
        select(
            Repository.id,
            Repository.full_name,
            func.count(Review.id).label("review_count"),
            func.coalesce(func.sum(Review.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(Review.output_tokens), 0).label("output_tokens"),
        )
        .outerjoin(PullRequest, PullRequest.repository_id == Repository.id)
        .outerjoin(Review, Review.pull_request_id == PullRequest.id)
        .group_by(Repository.id, Repository.full_name)
        .order_by(Repository.id)
    )
    repo_rows = (await session.execute(repo_stats_q)).all()

    # Severity distribution overall
    severity_q = (
        select(
            ReviewComment.severity,
            func.count(ReviewComment.id).label("cnt"),
        )
        .where(ReviewComment.severity.is_not(None))
        .group_by(ReviewComment.severity)
    )
    severity_rows = (await session.execute(severity_q)).all()
    severity_dist = {row.severity: row.cnt for row in severity_rows}

    # Status distribution
    status_q = select(Review.status, func.count(Review.id).label("cnt")).group_by(Review.status)
    status_rows = (await session.execute(status_q)).all()
    status_dist = {row.status: row.cnt for row in status_rows}

    total_reviews = sum(r.review_count for r in repo_rows)
    total_input = sum(r.input_tokens for r in repo_rows)
    total_output = sum(r.output_tokens for r in repo_rows)

    return {
        "total_reviews": total_reviews,
        "total_input_tokens": int(total_input),
        "total_output_tokens": int(total_output),
        "status_distribution": status_dist,
        "severity_distribution": severity_dist,
        "by_repository": [
            {
                "repository_id": r.id,
                "full_name": r.full_name,
                "review_count": r.review_count,
                "input_tokens": int(r.input_tokens),
                "output_tokens": int(r.output_tokens),
            }
            for r in repo_rows
        ],
    }
