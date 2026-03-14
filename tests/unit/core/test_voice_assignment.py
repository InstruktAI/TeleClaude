"""Characterization tests for teleclaude.core.voice_assignment."""

from __future__ import annotations

import pytest

from teleclaude.core.voice_assignment import VoiceConfig, get_voice_env_vars


class TestVoiceConfig:
    # VoiceConfig is a plain dataclass; field storage is the contract.
    # Behavioral impact of VoiceConfig values is covered by TestGetVoiceEnvVars.
    @pytest.mark.unit
    def test_stores_service_and_voice(self):
        vc = VoiceConfig(service_name="elevenlabs", voice="voice-abc")
        assert vc.service_name == "elevenlabs"
        assert vc.voice == "voice-abc"

    @pytest.mark.unit
    def test_empty_voice_allowed(self):
        vc = VoiceConfig(service_name="pyttsx3", voice="")
        assert vc.voice == ""


class TestGetVoiceEnvVars:
    @pytest.mark.unit
    def test_elevenlabs_sets_voice_id(self):
        vc = VoiceConfig(service_name="elevenlabs", voice="voice-xyz")
        env = get_voice_env_vars(vc)
        assert env.get("ELEVENLABS_VOICE_ID") == "voice-xyz"

    @pytest.mark.unit
    def test_macos_sets_macos_voice(self):
        vc = VoiceConfig(service_name="macos", voice="Samantha")
        env = get_voice_env_vars(vc)
        assert env.get("MACOS_VOICE") == "Samantha"

    @pytest.mark.unit
    def test_openai_sets_openai_voice(self):
        vc = VoiceConfig(service_name="openai", voice="alloy")
        env = get_voice_env_vars(vc)
        assert env.get("OPENAI_VOICE") == "alloy"

    @pytest.mark.unit
    def test_pyttsx3_returns_empty_dict(self):
        vc = VoiceConfig(service_name="pyttsx3", voice="")
        env = get_voice_env_vars(vc)
        assert env == {}

    @pytest.mark.unit
    def test_unknown_service_returns_empty_dict(self):
        vc = VoiceConfig(service_name="unknown_svc", voice="some-voice")
        env = get_voice_env_vars(vc)
        assert env == {}
