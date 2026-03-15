"""Characterization tests for teleclaude.stt.backends.openai_whisper."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import teleclaude.stt.backends.openai_whisper as openai_whisper


def test_ensure_client_requires_openai_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    backend = openai_whisper.OpenAIWhisperBackend()

    assert backend._ensure_client() is False


async def test_transcribe_raises_for_missing_audio_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    create = AsyncMock()
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr(openai_whisper, "AsyncOpenAI", lambda api_key: client)
    backend = openai_whisper.OpenAIWhisperBackend()

    with pytest.raises(FileNotFoundError):
        await backend.transcribe(str(tmp_path / "missing.wav"))


async def test_transcribe_passes_language_and_returns_stripped_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio_path = tmp_path / "voice.wav"
    audio_path.write_bytes(b"audio")
    create = AsyncMock(return_value=SimpleNamespace(text=" hello world \n"))
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setattr(openai_whisper, "AsyncOpenAI", lambda api_key: client)
    backend = openai_whisper.OpenAIWhisperBackend()

    result = await backend.transcribe(str(audio_path), language="en")

    assert result == "hello world"
    assert create.await_args.kwargs["model"] == "whisper-1"
    assert create.await_args.kwargs["language"] == "en"
    assert create.await_args.kwargs["file"].name.endswith("voice.wav")
