"""Unit tests for voice assignment module."""

from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.voice_assignment import (
    VoiceConfig,
    get_random_voice,
    get_voice_env_vars,
)


class TestVoiceConfig:
    """Tests for VoiceConfig dataclass."""

    def test_voice_config_creation(self) -> None:
        voice = VoiceConfig(service_name="elevenlabs", voice="abc123")
        assert voice.service_name == "elevenlabs"
        assert voice.voice == "abc123"


class TestGetRandomVoice:
    """Tests for get_random_voice function."""

    @pytest.mark.asyncio
    async def test_get_random_voice_returns_voice_from_manager(self) -> None:
        mock_manager = AsyncMock()
        mock_manager.get_random_voice_for_session.return_value = ("elevenlabs", "voice_id_123")

        with patch("teleclaude.core.voice_assignment._get_tts_manager", return_value=mock_manager):
            result = await get_random_voice()

        assert result is not None
        assert result.service_name == "elevenlabs"
        assert result.voice == "voice_id_123"

    @pytest.mark.asyncio
    async def test_get_random_voice_returns_none_when_no_voices(self) -> None:
        mock_manager = AsyncMock()
        mock_manager.get_random_voice_for_session.return_value = None

        with patch("teleclaude.core.voice_assignment._get_tts_manager", return_value=mock_manager):
            result = await get_random_voice()

        assert result is None

    @pytest.mark.asyncio
    async def test_get_random_voice_handles_empty_voice_name(self) -> None:
        mock_manager = AsyncMock()
        mock_manager.get_random_voice_for_session.return_value = ("pyttsx3", None)

        with patch("teleclaude.core.voice_assignment._get_tts_manager", return_value=mock_manager):
            result = await get_random_voice()

        assert result is not None
        assert result.service_name == "pyttsx3"
        assert result.voice == ""


class TestGetVoiceEnvVars:
    """Tests for get_voice_env_vars function."""

    def test_elevenlabs(self) -> None:
        voice = VoiceConfig(service_name="elevenlabs", voice="abc123")
        assert get_voice_env_vars(voice) == {"ELEVENLABS_VOICE_ID": "abc123"}

    def test_macos(self) -> None:
        voice = VoiceConfig(service_name="macos", voice="Daniel")
        assert get_voice_env_vars(voice) == {"MACOS_VOICE": "Daniel"}

    def test_openai(self) -> None:
        voice = VoiceConfig(service_name="openai", voice="nova")
        assert get_voice_env_vars(voice) == {"OPENAI_VOICE": "nova"}

    def test_pyttsx3_returns_empty(self) -> None:
        voice = VoiceConfig(service_name="pyttsx3", voice="")
        assert get_voice_env_vars(voice) == {}

    def test_unknown_service_returns_empty(self) -> None:
        voice = VoiceConfig(service_name="unknown", voice="test")
        assert get_voice_env_vars(voice) == {}
