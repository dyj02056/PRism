import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ReviewCommentOut:
    file_path: str | None
    line: int | None
    severity: str  # info | warning | critical
    body: str


@dataclass
class ReviewResult:
    summary: str
    comments: list[ReviewCommentOut] = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


SYSTEM_PROMPT = """You are a senior code reviewer. Review the given pull request diff.
Respond with ONLY valid JSON (no markdown fences) in this shape:
{
  "summary": "2-4 sentence overall review",
  "comments": [
    {
      "file_path": "path/to/file.py",
      "line": 42,
      "severity": "info|warning|critical",
      "body": "actionable comment"
    }
  ]
}
Rules:
- Prefer a few high-value comments over many nits.
- severity: critical = bugs/security, warning = design/perf, info = style/nit.
- If the diff is empty or trivial, return a short summary and empty comments.
"""


def _truncate_diff(diff: str, max_files: int, max_lines: int) -> str:
    files = re.split(r"(?=^diff --git )", diff, flags=re.MULTILINE)
    files = [f for f in files if f.strip()]
    if len(files) > max_files:
        files = files[:max_files]
        files.append("\n... (diff truncated: too many files)\n")
    text = "".join(files)
    lines = text.splitlines()
    if len(lines) > max_lines:
        text = "\n".join(lines[:max_lines]) + "\n... (diff truncated: too many lines)\n"
    return text


def _first_diff_file(diff: str) -> str | None:
    match = re.search(r"^diff --git a/\S+ b/(\S+)", diff, flags=re.MULTILINE)
    return match.group(1) if match else None


def _mock_result(diff: str) -> ReviewResult:
    has_content = bool(diff.strip())
    return ReviewResult(
        summary=(
            "Mock review: the PR looks generally fine. Consider adding tests for edge cases."
            if has_content
            else "Mock review: empty diff."
        ),
        # No line number: a fake line outside the real diff would make GitHub reject
        # the whole review (422). File-level comments are posted in the summary instead.
        comments=[
            ReviewCommentOut(
                file_path=_first_diff_file(diff),
                line=None,
                severity="info",
                body="[mock] Consider clarifying this variable name.",
            )
        ]
        if has_content
        else [],
        model="mock",
        input_tokens=0,
        output_tokens=0,
    )


def _parse_llm_json(text: str) -> dict[str, Any]:
    text = text.strip()
    # strip accidental markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


class LLMReviewer:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def review(self, diff: str) -> ReviewResult:
        settings = self.settings
        truncated = _truncate_diff(diff, settings.max_diff_files, settings.max_diff_lines)

        if settings.llm_mock or not settings.llm_api_key:
            logger.info("LLM mock mode enabled")
            return _mock_result(truncated)

        return await self._call_llm(truncated)

    async def _call_llm(self, diff: str) -> ReviewResult:
        settings = self.settings
        url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Review this pull request diff:\n\n{diff}",
                },
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage") or {}
        parsed = _parse_llm_json(content)

        comments: list[ReviewCommentOut] = []
        for c in parsed.get("comments") or []:
            comments.append(
                ReviewCommentOut(
                    file_path=c.get("file_path"),
                    line=c.get("line"),
                    severity=c.get("severity") or "info",
                    body=c.get("body") or "",
                )
            )

        return ReviewResult(
            summary=parsed.get("summary") or "",
            comments=comments,
            model=settings.llm_model,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )


def get_llm_reviewer() -> LLMReviewer:
    return LLMReviewer()
