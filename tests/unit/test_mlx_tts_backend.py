import shutil
from pathlib import Path

from teleclaude.tts.backends.mlx_tts import MLXTTSBackend


def test_resolve_cli_bin_prefers_env_var(monkeypatch, tmp_path: Path) -> None:
    """_resolve_cli_bin uses TELECLAUDE_MLX_TTS_CLI_BIN when set."""
    fake_cli = tmp_path / "custom_cli"
    fake_cli.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_cli.chmod(0o755)

    monkeypatch.setenv("TELECLAUDE_MLX_TTS_CLI_BIN", str(fake_cli))

    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    assert backend._resolve_cli_bin() == str(fake_cli)


def test_resolve_cli_bin_falls_back_to_which(monkeypatch, tmp_path: Path) -> None:
    """_resolve_cli_bin falls back to shutil.which when env var is not set."""
    monkeypatch.delenv("TELECLAUDE_MLX_TTS_CLI_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/mlx_audio.tts.generate")

    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    assert backend._resolve_cli_bin() == "/usr/local/bin/mlx_audio.tts.generate"


def test_resolve_cli_bin_returns_none_when_missing(monkeypatch, tmp_path: Path) -> None:
    """_resolve_cli_bin returns None when no binary is found."""
    monkeypatch.delenv("TELECLAUDE_MLX_TTS_CLI_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    # Ensure ~/.local/bin fallback also misses
    monkeypatch.setattr(Path, "exists", lambda self: False)

    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    assert backend._resolve_cli_bin() is None
