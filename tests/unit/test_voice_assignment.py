"""Unit tests for voice assignment module."""

from unittest.mock import MagicMock, patch

from teleclaude.core.voice_assignment import (
    VoiceConfig,
    get_random_voice,
    get_voice_env_vars,
)


class TestVoiceConfig:
    """Tests for VoiceConfig dataclass."""

    def test_voice_config_creation(self) -> None:
        """Test that VoiceConfig preserves provided fields on construction."""
        voice = VoiceConfig(
            service_name="elevenlabs",
            voice_name="abc123",
        )

        assert voice.service_name == "elevenlabs"
        assert voice.voice_name == "abc123"


class TestGetRandomVoice:
    """Tests for get_random_voice function."""

    def test_get_random_voice_returns_voice_from_manager(self) -> None:
        """Test that get_random_voice returns a voice when manager provides one."""
        mock_manager = MagicMock()
        mock_manager.get_random_voice_for_session.return_value = ("elevenlabs", "voice_id_123")

        with patch("teleclaude.core.voice_assignment._get_tts_manager", return_value=mock_manager):
            result = get_random_voice()

        assert result is not None
        assert result.service_name == "elevenlabs"
        assert result.voice_name == "voice_id_123"

    def test_get_random_voice_returns_none_when_no_voices(self) -> None:
        """Test that get_random_voice returns None when manager has no voices."""
        mock_manager = MagicMock()
        mock_manager.get_random_voice_for_session.return_value = None

        with patch("teleclaude.core.voice_assignment._get_tts_manager", return_value=mock_manager):
            result = get_random_voice()

        assert result is None

    def test_get_random_voice_handles_empty_voice_name(self) -> None:
        """Test that get_random_voice handles None voice_name by using empty string."""
        mock_manager = MagicMock()
        mock_manager.get_random_voice_for_session.return_value = ("pyttsx3", None)

        with patch("teleclaude.core.voice_assignment._get_tts_manager", return_value=mock_manager):
            result = get_random_voice()

        assert result is not None
        assert result.service_name == "pyttsx3"
        assert result.voice_name == ""


class TestGetVoiceEnvVars:
    """Tests for get_voice_env_vars function."""

    def test_get_voice_env_vars_elevenlabs(self) -> None:
        """Test that get_voice_env_vars returns ELEVENLABS_VOICE_ID for elevenlabs service."""
        voice = VoiceConfig(service_name="elevenlabs", voice_name="abc123")

        result = get_voice_env_vars(voice)

        assert result == {"ELEVENLABS_VOICE_ID": "abc123"}

    def test_get_voice_env_vars_macos(self) -> None:
        """Test that get_voice_env_vars returns MACOS_VOICE for macos service."""
        voice = VoiceConfig(service_name="macos", voice_name="Daniel")

        result = get_voice_env_vars(voice)

        assert result == {"MACOS_VOICE": "Daniel"}

    def test_get_voice_env_vars_openai(self) -> None:
        """Test that get_voice_env_vars returns OPENAI_VOICE for openai service."""
        voice = VoiceConfig(service_name="openai", voice_name="nova")

        result = get_voice_env_vars(voice)

        assert result == {"OPENAI_VOICE": "nova"}

    def test_get_voice_env_vars_pyttsx3(self) -> None:
        """Test that get_voice_env_vars returns empty dict for pyttsx3 service."""
        voice = VoiceConfig(service_name="pyttsx3", voice_name="")

        result = get_voice_env_vars(voice)

        assert result == {}

    def test_get_voice_env_vars_unknown_service(self) -> None:
        """Test that get_voice_env_vars returns empty dict for unknown service."""
        voice = VoiceConfig(service_name="unknown", voice_name="test")

        result = get_voice_env_vars(voice)

        assert result == {}
