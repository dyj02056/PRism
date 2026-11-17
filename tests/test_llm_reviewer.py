import pytest

from app.core.config import get_settings
from app.services.llm_reviewer import LLMReviewer, _mock_result


@pytest.mark.asyncio
async def test_mock_mode_returns_fixed_shape(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("LLM_MOCK", "true")
    get_settings.cache_clear()

    reviewer = LLMReviewer()
    result = await reviewer.review("diff --git a/x.py\n+hello")

    assert result.summary
    assert result.model == "mock"
    assert isinstance(result.comments, list)
    assert result.input_tokens == 0


def test_mock_result_has_no_fake_line():
    """Mock comments must not point at lines outside the diff (GitHub would 422)."""
    r = _mock_result("diff --git a/src/x.py b/src/x.py\n+hello")
    assert r.comments[0].file_path == "src/x.py"
    assert r.comments[0].line is None


def test_mock_result_empty_diff():
    r = _mock_result("")
    assert r.comments == []
    assert "empty" in r.summary.lower() or "Mock" in r.summary
