"""Characterization tests for teleclaude.tts.models."""

from __future__ import annotations

from teleclaude.tts.models import EventConfig, ServiceConfig, ServiceVoiceConfig, TTSConfig


def test_event_config_stores_enabled_and_message() -> None:
    config = EventConfig(enabled=True, message="Session finished")

    assert config.enabled is True
    assert config.message == "Session finished"


def test_service_voice_config_defaults_voice_id_to_none() -> None:
    voice = ServiceVoiceConfig(name="Samantha")

    assert voice.name == "Samantha"
    assert voice.voice_id is None


def test_service_config_uses_a_fresh_voice_list_per_instance() -> None:
    left = ServiceConfig(enabled=True)
    right = ServiceConfig(enabled=False)

    left.voices.append(ServiceVoiceConfig(name="Alloy", voice_id="voice-1"))

    assert left.voices == [ServiceVoiceConfig(name="Alloy", voice_id="voice-1")]
    assert right.voices == []


def test_tts_config_uses_fresh_event_and_service_dicts_per_instance() -> None:
    left = TTSConfig(enabled=True)
    right = TTSConfig(enabled=False)

    left.events["session_complete"] = EventConfig(enabled=True, message="Done")
    left.services["macos"] = ServiceConfig(enabled=True)

    assert left.events["session_complete"].message == "Done"
    assert "session_complete" not in right.events
    assert "macos" not in right.services
