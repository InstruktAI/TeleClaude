"""Characterization tests for teleclaude.core.summarizer."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace, TracebackType
from unittest.mock import AsyncMock

import pytest

from teleclaude.config import SummarizerConfig, SummarizerLocalConfig

# _build_*_prompt and _parse_* helpers: pure functions tested directly because
# the public async functions (generate_session_title, summarize_agent_output)
# require a live LLM API call with API keys. Testing helpers pins the prompt
# structure and parsing contracts without infrastructure.
from teleclaude.core.summarizer import (
    _DEFAULT_MODELS,
    SUMMARY_SCHEMA,
    TITLE_SCHEMA,
    _build_agent_output_summary_prompt,
    _build_session_title_prompt,
    _call_summarizer,
    _parse_summary_response,
    _parse_title_response,
    generate_session_title,
    summarize_agent_output,
)

_EXPECTED_PROVIDERS = {"openai", "anthropic", "google"}
_CLOUD_PRIORITY = ["openai", "anthropic", "google"]


def _pin_summarizer(monkeypatch: pytest.MonkeyPatch, summ: SummarizerConfig) -> None:
    """Pin the global summarizer config so dispatch tests are deterministic."""
    monkeypatch.setattr("teleclaude.core.summarizer.config.summarizer", summ)


class TestSummarizerModels:
    @pytest.mark.unit
    def test_covers_three_cloud_providers(self):
        assert set(_DEFAULT_MODELS) == _EXPECTED_PROVIDERS

    @pytest.mark.unit
    def test_default_models_are_dateless_aliases(self):
        # No 8-digit date suffix (e.g. 20251001) so defaults track the latest.
        assert all(model and not re.search(r"20\d{6}", model) for model in _DEFAULT_MODELS.values())


class TestBuildSessionTitlePrompt:
    @pytest.mark.unit
    def test_includes_conversation_turns(self):
        turns = [("user", "hello"), ("assistant", "hi there")]
        prompt = _build_session_title_prompt(turns)
        assert "User: hello" in prompt
        assert "Assistant: hi there" in prompt

    @pytest.mark.unit
    def test_single_turn_prompt_contains_role(self):
        turns = [("user", "fix the bug")]
        prompt = _build_session_title_prompt(turns)
        assert "User: fix the bug" in prompt


class TestBuildAgentOutputSummaryPrompt:
    @pytest.mark.unit
    def test_includes_agent_output(self):
        prompt = _build_agent_output_summary_prompt("The agent did something", 30)
        assert "The agent did something" in prompt

    @pytest.mark.unit
    def test_includes_max_words_limit(self):
        prompt = _build_agent_output_summary_prompt("some output", 25)
        assert "25" in prompt


class TestParseTitleResponse:
    @pytest.mark.unit
    def test_parses_valid_json_title(self):
        text = json.dumps({"title": "Fix authentication bug"})
        result = _parse_title_response(text)
        assert result == "Fix authentication bug"

    @pytest.mark.unit
    def test_title_truncated_at_70_chars(self):
        long_title = "A" * 100
        text = json.dumps({"title": long_title})
        result = _parse_title_response(text)
        assert result is not None
        assert len(result) <= 70

    @pytest.mark.unit
    def test_empty_title_raises(self):
        text = json.dumps({"title": ""})
        with pytest.raises(ValueError):
            _parse_title_response(text)


class TestParseSummaryResponse:
    @pytest.mark.unit
    def test_parses_valid_json_summary(self):
        text = json.dumps({"summary": "I fixed the login bug"})
        result = _parse_summary_response(text)
        assert result == "I fixed the login bug"

    @pytest.mark.unit
    def test_empty_summary_raises(self):
        text = json.dumps({"summary": ""})
        with pytest.raises(ValueError):
            _parse_summary_response(text)


class TestGenerateSessionTitle:
    @pytest.mark.unit
    async def test_empty_turns_raises(self):
        with pytest.raises(ValueError, match="Empty session title context"):
            await generate_session_title([])


class TestSummarizeAgentOutput:
    @pytest.mark.unit
    async def test_empty_output_raises(self):
        with pytest.raises(ValueError, match="Empty agent output"):
            await summarize_agent_output("")

    @pytest.mark.unit
    async def test_whitespace_output_raises(self):
        with pytest.raises(ValueError, match="Empty agent output"):
            await summarize_agent_output("   ")


class _FakeAnthropicClient:
    instances: list[_FakeAnthropicClient] = []

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.closed = False
        self.beta = SimpleNamespace(
            messages=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(content=[SimpleNamespace(text='{"title":"ok"}')]))
            )
        )
        _FakeAnthropicClient.instances.append(self)

    async def __aenter__(self) -> _FakeAnthropicClient:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.closed = True


class _FakeOpenAIClient:
    instances: list[_FakeOpenAIClient] = []

    def __init__(self, api_key: str, base_url: str | None = None):
        self.api_key = api_key
        self.base_url = base_url
        self.closed = False
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary":"done"}'))]
                    )
                )
            )
        )
        _FakeOpenAIClient.instances.append(self)

    async def __aenter__(self) -> _FakeOpenAIClient:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.closed = True


class TestCallSummarizerDispatch:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_anthropic_client_is_closed_after_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _FakeAnthropicClient.instances = []
        _pin_summarizer(monkeypatch, SummarizerConfig(provider_priority=_CLOUD_PRIORITY))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setattr("teleclaude.core.summarizer.AsyncAnthropic", _FakeAnthropicClient)

        result = await _call_summarizer("prompt", TITLE_SCHEMA, _parse_title_response)

        assert result == "ok"
        assert len(_FakeAnthropicClient.instances) == 1
        assert _FakeAnthropicClient.instances[0].closed is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_openai_client_is_closed_after_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _FakeOpenAIClient.instances = []
        _pin_summarizer(monkeypatch, SummarizerConfig(provider_priority=_CLOUD_PRIORITY))
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setattr("teleclaude.core.summarizer.AsyncOpenAI", _FakeOpenAIClient)

        result = await _call_summarizer("prompt", SUMMARY_SCHEMA, _parse_summary_response)

        assert result == "done"
        assert len(_FakeOpenAIClient.instances) == 1
        assert _FakeOpenAIClient.instances[0].closed is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_missing_keys_are_skipped_to_reach_google(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _FakeOpenAIClient.instances = []
        _pin_summarizer(monkeypatch, SummarizerConfig(provider_priority=_CLOUD_PRIORITY))
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        monkeypatch.setattr("teleclaude.core.summarizer.AsyncOpenAI", _FakeOpenAIClient)

        result = await _call_summarizer("prompt", SUMMARY_SCHEMA, _parse_summary_response)

        assert result == "done"
        # Google routes through the OpenAI-compatible client with Gemini's base_url.
        assert _FakeOpenAIClient.instances[0].base_url is not None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_enabled_local_provider_is_tried_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _FakeOpenAIClient.instances = []
        local = SummarizerLocalConfig(enabled=True, base_url="http://localhost:1234/v1", model="local-model")
        _pin_summarizer(monkeypatch, SummarizerConfig(local=local, provider_priority=_CLOUD_PRIORITY))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")  # would win if local were skipped
        monkeypatch.setattr("teleclaude.core.summarizer.AsyncOpenAI", _FakeOpenAIClient)

        result = await _call_summarizer("prompt", SUMMARY_SCHEMA, _parse_summary_response)

        assert result == "done"
        assert _FakeOpenAIClient.instances[0].base_url == "http://localhost:1234/v1"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_keys_and_no_local_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _pin_summarizer(monkeypatch, SummarizerConfig(provider_priority=_CLOUD_PRIORITY))
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

        with pytest.raises(RuntimeError):
            await _call_summarizer("prompt", SUMMARY_SCHEMA, _parse_summary_response)
