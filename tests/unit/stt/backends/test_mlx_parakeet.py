"""Characterization tests for teleclaude.stt.backends.mlx_parakeet."""

from __future__ import annotations

from pathlib import Path

import pytest

import teleclaude.stt.backends.mlx_parakeet as mlx_parakeet


def test_init_rejects_missing_local_model_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing_model = tmp_path / "missing-model"
    monkeypatch.setattr(mlx_parakeet, "resolve_model_ref", lambda value: str(missing_model))
    monkeypatch.setattr("teleclaude.mlx_utils.is_local_path", lambda value: True)

    with pytest.raises(FileNotFoundError):
        mlx_parakeet.MLXParakeetBackend()


async def test_transcribe_uses_cli_fallback_when_cli_bin_is_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cli_bin = tmp_path / "mlx_audio.stt.generate"
    cli_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"audio")
    monkeypatch.setenv(mlx_parakeet.CLI_BIN_ENV_VAR, str(cli_bin))
    monkeypatch.setattr(mlx_parakeet, "resolve_model_ref", lambda value: "mlx-community/parakeet")
    backend = mlx_parakeet.MLXParakeetBackend()
    monkeypatch.setattr(backend, "_transcribe_cli", lambda path, language=None: f"{Path(path).name}:{language}")

    result = await backend.transcribe(str(audio_path), language="en")

    assert result == "sample.wav:en"


async def test_transcribe_raises_runtime_error_when_backend_cannot_initialize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"audio")
    monkeypatch.delenv(mlx_parakeet.CLI_BIN_ENV_VAR, raising=False)
    monkeypatch.setattr(mlx_parakeet.shutil, "which", lambda _name: None)
    monkeypatch.setattr(mlx_parakeet, "resolve_model_ref", lambda value: "mlx-community/parakeet")
    backend = mlx_parakeet.MLXParakeetBackend()
    monkeypatch.setattr(backend, "_ensure_model", lambda: False)

    with pytest.raises(RuntimeError, match="Parakeet STT unavailable"):
        await backend.transcribe(str(audio_path))
