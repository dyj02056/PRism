import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Thin async client for PR diff and comment APIs."""

    def __init__(
        self,
        token: str | None = None,
        base_url: str = GITHUB_API,
        timeout: float = 30.0,
    ) -> None:
        settings = get_settings()
        self.token = token or settings.github_token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def get_pull_diff(self, full_name: str, pr_number: int) -> str:
        """Fetch unified diff for a pull request.

        Uses Accept: application/vnd.github.v3.diff
        """
        url = f"{self.base_url}/repos/{full_name}/pulls/{pr_number}"
        headers = self._headers()
        headers["Accept"] = "application/vnd.github.v3.diff"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text

    async def create_issue_comment(
        self, full_name: str, pr_number: int, body: str
    ) -> dict[str, Any]:
        """Post a comment on the PR (issue comments endpoint)."""
        url = f"{self.base_url}/repos/{full_name}/issues/{pr_number}/comments"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers=self._headers(),
                json={"body": body},
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data

    async def create_pull_review(
        self,
        full_name: str,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
        comments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a pull request review with optional line comments.

        comments item example:
          {"path": "src/main.py", "line": 10, "body": "nit: ..."}
        """
        url = f"{self.base_url}/repos/{full_name}/pulls/{pr_number}/reviews"
        payload: dict[str, Any] = {"body": body, "event": event}
        if comments:
            payload["comments"] = comments

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                url,
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
            return data


def get_github_client() -> GitHubClient:
    return GitHubClient()
