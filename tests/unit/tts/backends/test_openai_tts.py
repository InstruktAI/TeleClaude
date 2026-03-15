"""Characterization tests for teleclaude.tts.backends.openai_tts."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest

from teleclaude.tts.backends.openai_tts import OpenAITTSBackend


def test_speak_returns_false_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert OpenAITTSBackend().speak("hello", "nova") is False


def test_speak_writes_audio_plays_file_and_cleans_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: dict[str, Any] = {}  # guard: loose-dict - Test helper payloads intentionally vary by scenario.
    run = Mock(return_value=SimpleNamespace(returncode=0))

    class FakeResponse:
        def write_to_file(self, path: str) -> None:
            calls["audio_path"] = path
            Path(path).write_bytes(b"audio")

    class FakeOpenAI:
        def __init__(self, api_key: str) -> None:
            calls["api_key"] = api_key
            self.audio = types.SimpleNamespace(speech=types.SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            calls["create"] = kwargs
            return FakeResponse()

    openai_module = types.ModuleType("openai")
    openai_module.OpenAI = FakeOpenAI
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr("teleclaude.tts.backends.openai_tts.subprocess.run", run)

    with patch.dict(sys.modules, {"openai": openai_module}):
        assert OpenAITTSBackend().speak("hello", "nova") is True

    assert calls["api_key"] == "secret"
    assert calls["create"] == {"model": "gpt-4o-mini-tts", "voice": "nova", "input": "hello"}
    run.assert_called_once()
    assert not Path(str(calls["audio_path"])).exists()
