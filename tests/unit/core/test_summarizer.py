"""Characterization tests for teleclaude.core.summarizer."""

from __future__ import annotations

import json
from types import SimpleNamespace, TracebackType
from unittest.mock import AsyncMock

import pytest

# _build_*_prompt and _parse_* helpers: pure functions tested directly because
# the public async functions (generate_session_title, summarize_agent_output)
# require a live LLM API call with API keys. Testing helpers pins the prompt
# structure and parsing contracts without infrastructure.
from teleclaude.core.summarizer import (
    SUMMARY_MODEL_ANTHROPIC,
    SUMMARY_MODEL_OPENAI,
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


class TestSummaryConstants:
    @pytest.mark.unit
    def test_anthropic_model_is_string(self):
        assert SUMMARY_MODEL_ANTHROPIC == "claude-haiku-4-5-20251001"

    @pytest.mark.unit
    def test_openai_model_is_string(self):
        assert isinstance(SUMMARY_MODEL_OPENAI, str)
        assert len(SUMMARY_MODEL_OPENAI) > 0

    @pytest.mark.unit
    def test_title_schema_has_required_fields(self):
        assert "title" in TITLE_SCHEMA["properties"]  # type: ignore[operator]
        assert "title" in TITLE_SCHEMA["required"]  # type: ignore[operator]

    @pytest.mark.unit
    def test_summary_schema_has_required_fields(self):
        assert "summary" in SUMMARY_SCHEMA["properties"]  # type: ignore[operator]
        assert "summary" in SUMMARY_SCHEMA["required"]  # type: ignore[operator]


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


class TestCallSummarizerLifecycle:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_anthropic_client_is_closed_after_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeAnthropicClient:
            instances: list[FakeAnthropicClient] = []

            def __init__(self, api_key: str):
                self.api_key = api_key
                self.closed = False
                self.beta = SimpleNamespace(
                    messages=SimpleNamespace(
                        create=AsyncMock(return_value=SimpleNamespace(content=[SimpleNamespace(text='{"title":"ok"}')]))
                    )
                )
                FakeAnthropicClient.instances.append(self)

            async def __aenter__(self) -> FakeAnthropicClient:
                return self

            async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc: BaseException | None,
                tb: TracebackType | None,
            ) -> None:
                self.closed = True

        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr("teleclaude.core.summarizer.AsyncAnthropic", FakeAnthropicClient)

        result = await _call_summarizer("prompt", TITLE_SCHEMA, _parse_title_response)

        assert result == "ok"
        assert len(FakeAnthropicClient.instances) == 1
        assert FakeAnthropicClient.instances[0].closed is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_openai_client_is_closed_after_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeOpenAIClient:
            instances: list[FakeOpenAIClient] = []

            def __init__(self, api_key: str):
                self.api_key = api_key
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
                FakeOpenAIClient.instances.append(self)

            async def __aenter__(self) -> FakeOpenAIClient:
                return self

            async def __aexit__(
                self,
                exc_type: type[BaseException] | None,
                exc: BaseException | None,
                tb: TracebackType | None,
            ) -> None:
                self.closed = True

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setattr("teleclaude.core.summarizer.AsyncOpenAI", FakeOpenAIClient)

        result = await _call_summarizer("prompt", SUMMARY_SCHEMA, _parse_summary_response)

        assert result == "done"
        assert len(FakeOpenAIClient.instances) == 1
        assert FakeOpenAIClient.instances[0].closed is True
