"""Characterization tests for teleclaude.tts.backends.elevenlabs."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from teleclaude.tts.backends.elevenlabs import ElevenLabsBackend


def test_speak_returns_false_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)

    assert ElevenLabsBackend().speak("hello", "voice-1") is False


def test_speak_returns_false_without_voice_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "secret")

    assert ElevenLabsBackend().speak("hello", None) is False


def test_speak_uses_client_convert_and_play(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}  # guard: loose-dict - Test helper payloads intentionally vary by scenario.
    play = Mock()

    class FakeElevenLabs:
        def __init__(self, api_key: str) -> None:
            calls["api_key"] = api_key
            self.text_to_speech = SimpleNamespace(convert=self.convert)

        def convert(self, **kwargs):
            calls["convert"] = kwargs
            return "audio-bytes"

    monkeypatch.setenv("ELEVENLABS_API_KEY", "secret")
    monkeypatch.setattr("teleclaude.tts.backends.elevenlabs.ElevenLabs", FakeElevenLabs)
    monkeypatch.setattr("teleclaude.tts.backends.elevenlabs.play", play)

    assert ElevenLabsBackend().speak("hello", "voice-1") is True

    assert calls["api_key"] == "secret"
    assert calls["convert"] == {
        "text": "hello",
        "voice_id": "voice-1",
        "model_id": "eleven_flash_v2_5",
        "output_format": "mp3_44100_128",
    }
    play.assert_called_once_with("audio-bytes")
