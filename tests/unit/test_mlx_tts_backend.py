import shutil
from pathlib import Path
from unittest.mock import patch

import teleclaude.tts.backends.mlx_tts as mlx_tts
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


def test_ensure_model_cli_only_does_not_import_mlx_audio() -> None:
    """When CLI backend exists, mlx_audio import must not be attempted."""
    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    backend._service_name = "kokoro"
    backend._cli_bin = "/tmp/mlx_audio.tts.generate"
    backend._model = None
    backend._model_ref = "mlx-community/Kokoro-82M-bf16"
    backend._params = {}

    with patch.object(mlx_tts, "import_module", side_effect=AssertionError("should not import mlx_audio")):
        assert backend._ensure_model() is True


def test_build_cli_command_uses_uv_for_python_script_backend(monkeypatch, tmp_path: Path) -> None:
    """Python-script CLI backends are invoked through uv-run module execution."""
    script = tmp_path / "mlx_audio.tts.generate"
    script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    script.chmod(0o755)

    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    backend._service_name = "kokoro"
    backend._cli_bin = str(script)
    backend._params = {}
    backend._model_ref = "mlx-community/Kokoro-82M-bf16"

    monkeypatch.setattr(mlx_tts, "_REPO_ROOT", tmp_path)
    cmd = backend._build_cli_command(text="hi", voice="nova", file_prefix="/tmp/tts")

    assert cmd[:5] == ["uv", "run", "--quiet", "--project", str(tmp_path)]
    assert cmd[5:9] == ["--extra", "mlx", "--with", "pip"]
    assert cmd[9:12] == ["python", "-m", "mlx_audio.tts.generate"]


def test_build_cli_command_uses_binary_directly_for_non_script(monkeypatch, tmp_path: Path) -> None:
    """Binary CLI executables are kept as direct invocations."""
    binary = tmp_path / "mlx_audio.tts.generate"
    binary.write_text("binary", encoding="utf-8")
    binary.chmod(0o755)

    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    backend._service_name = "kokoro"
    backend._cli_bin = str(binary)
    backend._params = {}
    backend._model_ref = "mlx-community/Kokoro-82M-bf16"

    cmd = backend._build_cli_command(text="hi", voice="nova", file_prefix="/tmp/tts")
    assert cmd[0] == str(binary)
    assert cmd[1:3] == ["--model", "mlx-community/Kokoro-82M-bf16"]
