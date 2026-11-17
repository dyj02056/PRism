from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PullRequest, Repository, Review
from app.db.session import get_db

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.get("")
async def list_repositories(
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    result = await session.execute(select(Repository).order_by(Repository.id.desc()))
    repos = result.scalars().all()
    return [
        {
            "id": r.id,
            "github_repo_id": r.github_repo_id,
            "full_name": r.full_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in repos
    ]


@router.get("/{repo_id}/reviews")
async def list_repo_reviews(
    repo_id: int,
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo = await session.get(Repository, repo_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository {repo_id} not found",
        )

    base = (
        select(Review)
        .join(PullRequest, Review.pull_request_id == PullRequest.id)
        .where(PullRequest.repository_id == repo_id)
    )
    if status_filter:
        base = base.where(Review.status == status_filter)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_q)).scalar_one()

    offset = (page - 1) * page_size
    result = await session.execute(base.order_by(Review.id.desc()).offset(offset).limit(page_size))
    reviews = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "pull_request_id": r.pull_request_id,
                "status": r.status,
                "summary": r.summary,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "error": r.error,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in reviews
        ],
    }
