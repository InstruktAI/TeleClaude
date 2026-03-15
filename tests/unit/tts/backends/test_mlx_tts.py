"""Characterization tests for teleclaude.tts.backends.mlx_tts."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import teleclaude.tts.backends.mlx_tts as mlx_tts


def test_init_rejects_missing_local_model_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing_model = tmp_path / "missing-model"
    monkeypatch.setattr(mlx_tts, "resolve_model_ref", lambda value: str(missing_model))
    monkeypatch.setattr("teleclaude.mlx_utils.is_local_path", lambda value: True)

    with pytest.raises(FileNotFoundError):
        mlx_tts.MLXTTSBackend("narrator", "ignored")


def test_speak_uses_cli_fallback_when_model_is_not_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mlx_tts, "resolve_model_ref", lambda value: value)
    monkeypatch.setattr("teleclaude.mlx_utils.is_local_path", lambda value: False)
    backend = mlx_tts.MLXTTSBackend("narrator", "repo/model")
    backend._cli_bin = "mlx_audio.tts.generate"
    speak_cli = Mock(return_value=True)
    monkeypatch.setattr(backend, "_ensure_model", lambda: True)
    monkeypatch.setattr(backend, "_speak_cli", speak_cli)

    assert backend.speak("hello") is True
    speak_cli.assert_called_once_with("hello", "narrator")


def test_speak_uses_local_generation_when_model_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mlx_tts, "resolve_model_ref", lambda value: value)
    monkeypatch.setattr("teleclaude.mlx_utils.is_local_path", lambda value: False)
    backend = mlx_tts.MLXTTSBackend("narrator", "repo/model")
    backend._cli_bin = None
    backend._model = SimpleNamespace(config=SimpleNamespace(tts_model_type="voice_design"))
    speak_local = Mock(return_value=True)
    monkeypatch.setattr(backend, "_ensure_model", lambda: True)
    monkeypatch.setattr(backend, "_speak_local", speak_local)

    assert backend.speak("hello", "alloy") is True
    speak_local.assert_called_once_with("hello", "alloy", "voice_design")
