"""Unit tests for voice assignment module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from teleclaude.core.voice_assignment import (
    VoiceConfig,
    get_random_voice,
    get_voice_env_vars,
    load_voices,
)


class TestVoiceConfig:
    """Tests for VoiceConfig dataclass."""

    def test_voice_config_creation(self) -> None:
        """Test that VoiceConfig preserves provided fields on construction."""
        voice = VoiceConfig(
            name="Test Voice",
            elevenlabs_id="abc123",
            macos_voice="Daniel",
            openai_voice="nova",
        )

        assert voice.name == "Test Voice"
        assert voice.elevenlabs_id == "abc123"
        assert voice.macos_voice == "Daniel"
        assert voice.openai_voice == "nova"


class TestLoadVoices:
    """Tests for load_voices function."""

    def test_load_voices_file_not_found_returns_empty_list(self) -> None:
        """Test that load_voices returns empty list when config path is missing."""
        with patch.object(Path, "exists", return_value=False):
            result = load_voices()

        assert result == []

    def test_load_voices_valid_config(self) -> None:
        """Test that load_voices parses valid JSON into VoiceConfig entries."""
        config_data = {
            "voices": [
                {
                    "name": "Voice 1",
                    "elevenlabs_id": "id1",
                    "macos_voice": "Daniel",
                    "openai_voice": "nova",
                },
                {
                    "name": "Voice 2",
                    "elevenlabs_id": "id2",
                    "macos_voice": "Samantha",
                    "openai_voice": "echo",
                },
            ]
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = Path(f.name)

        try:
            with patch("teleclaude.core.voice_assignment.VOICES_CONFIG_PATH", temp_path):
                result = load_voices()

            assert len(result) == 2
            assert result[0].name == "Voice 1"
            assert result[0].elevenlabs_id == "id1"
            assert result[1].name == "Voice 2"
            assert result[1].macos_voice == "Samantha"
        finally:
            temp_path.unlink()

    def test_load_voices_invalid_json_returns_empty_list(self) -> None:
        """Test that load_voices returns empty list when JSON decoding fails."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json {{{")
            temp_path = Path(f.name)

        try:
            with patch("teleclaude.core.voice_assignment.VOICES_CONFIG_PATH", temp_path):
                result = load_voices()

            assert result == []
        finally:
            temp_path.unlink()

    def test_load_voices_missing_fields_uses_defaults(self) -> None:
        """Test that load_voices fills missing fields with empty string defaults."""
        config_data = {"voices": [{"name": "Minimal Voice"}]}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = Path(f.name)

        try:
            with patch("teleclaude.core.voice_assignment.VOICES_CONFIG_PATH", temp_path):
                result = load_voices()

            assert len(result) == 1
            assert result[0].name == "Minimal Voice"
            assert result[0].elevenlabs_id == ""
            assert result[0].macos_voice == ""
            assert result[0].openai_voice == ""
        finally:
            temp_path.unlink()


class TestGetRandomVoice:
    """Tests for get_random_voice function."""

    def test_get_random_voice_returns_voice_from_config(self) -> None:
        """Test that get_random_voice returns one of the loaded voices when available."""
        voices = [
            VoiceConfig(name="Voice 1", elevenlabs_id="id1", macos_voice="Daniel", openai_voice="nova"),
            VoiceConfig(name="Voice 2", elevenlabs_id="id2", macos_voice="Samantha", openai_voice="echo"),
        ]

        with patch("teleclaude.core.voice_assignment.load_voices", return_value=voices):
            result = get_random_voice()

        assert result in voices

    def test_get_random_voice_returns_none_when_no_voices(self) -> None:
        """Test that get_random_voice returns None when the voice list is empty."""
        with patch("teleclaude.core.voice_assignment.load_voices", return_value=[]):
            result = get_random_voice()

        assert result is None


class TestGetVoiceEnvVars:
    """Tests for get_voice_env_vars function."""

    def test_get_voice_env_vars_all_fields(self) -> None:
        """Test that get_voice_env_vars emits all env vars when fields are populated."""
        voice = VoiceConfig(
            name="Test Voice",
            elevenlabs_id="abc123",
            macos_voice="Daniel",
            openai_voice="nova",
        )

        result = get_voice_env_vars(voice)

        assert result == {
            "ELEVENLABS_VOICE_ID": "abc123",
            "MACOS_VOICE": "Daniel",
            "OPENAI_VOICE": "nova",
        }

    def test_get_voice_env_vars_partial_fields(self) -> None:
        """Test that get_voice_env_vars omits env vars for empty fields."""
        voice = VoiceConfig(
            name="Partial Voice",
            elevenlabs_id="",
            macos_voice="Daniel",
            openai_voice="",
        )

        result = get_voice_env_vars(voice)

        assert result == {"MACOS_VOICE": "Daniel"}
        assert "ELEVENLABS_VOICE_ID" not in result
        assert "OPENAI_VOICE" not in result

    def test_get_voice_env_vars_no_fields(self) -> None:
        """Test that get_voice_env_vars returns empty dict when all fields are blank."""
        voice = VoiceConfig(
            name="Empty Voice",
            elevenlabs_id="",
            macos_voice="",
            openai_voice="",
        )

        result = get_voice_env_vars(voice)

        assert result == {}
