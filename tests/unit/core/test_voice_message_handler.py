"""Characterization tests for teleclaude.core.voice_message_handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.voice_message_handler import (
    DEFAULT_TRANSCRIBE_LANGUAGE,
    transcribe_voice_with_retry,
)


class TestDefaultTranscribeLanguage:
    @pytest.mark.unit
    def test_default_language_value(self):
        assert DEFAULT_TRANSCRIBE_LANGUAGE == "en"


class TestTranscribeVoiceWithRetry:
    @pytest.mark.unit
    async def test_returns_text_on_success(self):
        with patch(
            "teleclaude.core.voice_message_handler.transcribe_voice",
            new=AsyncMock(return_value="hello world"),
        ):
            text, error = await transcribe_voice_with_retry("/tmp/audio.ogg")
        assert text == "hello world"
        assert error is None

    @pytest.mark.unit
    async def test_returns_none_on_all_failures(self):
        with patch(
            "teleclaude.core.voice_message_handler.transcribe_voice",
            new=AsyncMock(side_effect=RuntimeError("STT failed")),
        ):
            text, error = await transcribe_voice_with_retry("/tmp/audio.ogg", max_retries=0)
        assert text is None
        assert error is not None

    @pytest.mark.unit
    async def test_succeeds_on_second_attempt(self):
        call_count = 0

        async def flaky_transcribe(path: str, lang: str | None = None) -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("transient error")
            return "transcribed text"

        with patch(
            "teleclaude.core.voice_message_handler.transcribe_voice",
            new=flaky_transcribe,
        ):
            text, error = await transcribe_voice_with_retry("/tmp/audio.ogg", max_retries=1)
        assert text == "transcribed text"
        assert error is None


class TestInitVoiceHandler:
    @pytest.mark.unit
    def test_init_with_api_key_sets_env_var(self):
        import os

        from teleclaude.core.voice_message_handler import init_voice_handler

        # Ensure the env var is not already set to a conflicting value
        original = os.environ.pop("OPENAI_API_KEY", None)
        try:
            init_voice_handler(api_key="test-key-123")
            assert os.environ.get("OPENAI_API_KEY") == "test-key-123"
        finally:
            if original is not None:
                os.environ["OPENAI_API_KEY"] = original
            else:
                os.environ.pop("OPENAI_API_KEY", None)

    @pytest.mark.unit
    def test_init_without_api_key_does_not_raise(self):
        from teleclaude.core.voice_message_handler import init_voice_handler

        # Should be a no-op, not raise
        init_voice_handler()
