import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
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


def test_ensure_model_prefers_cli_backend_when_cli_exists() -> None:
    """When a CLI exists, keep MLX generation out of the daemon process."""
    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    backend._service_name = "kokoro"
    backend._cli_bin = "/tmp/mlx_audio.tts.generate"
    backend._model = None
    backend._model_ref = "mlx-community/Kokoro-82M-bf16"
    backend._params = {}

    with (
        patch.object(mlx_tts, "import_module") as import_module,
        patch.object(mlx_tts, "_mlx_audio_import_attempted", False),
        patch.object(mlx_tts, "generate_audio", None),
        patch.object(mlx_tts, "load_model", None),
        patch.object(mlx_tts, "mlx_audio_import_error", None),
    ):
        assert backend._ensure_model() is True
        assert backend._model is None
        import_module.assert_not_called()


def test_ensure_model_ignores_import_failures_when_cli_exists() -> None:
    """CLI mode should not touch mlx_audio imports at all."""
    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    backend._service_name = "kokoro"
    backend._cli_bin = "/tmp/mlx_audio.tts.generate"
    backend._model = None
    backend._model_ref = "mlx-community/Kokoro-82M-bf16"
    backend._params = {}

    with (
        patch.object(mlx_tts, "import_module", side_effect=ImportError("mlx missing")) as import_module,
        patch.object(mlx_tts, "_mlx_audio_import_attempted", False),
        patch.object(mlx_tts, "generate_audio", None),
        patch.object(mlx_tts, "load_model", None),
        patch.object(mlx_tts, "mlx_audio_import_error", None),
    ):
        assert backend._ensure_model() is True
        assert backend._model is None
        import_module.assert_not_called()


def test_build_cli_command_uses_repo_uv_run_for_python_entrypoint(tmp_path: Path) -> None:
    """Python-script entrypoints should run through the repo mlx environment."""
    script = tmp_path / "mlx_audio.tts.generate"
    script.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    script.chmod(0o755)

    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    backend._service_name = "kokoro"
    backend._cli_bin = str(script)
    backend._params = {}
    backend._model_ref = "mlx-community/Kokoro-82M-bf16"

    cmd = backend._build_cli_command(text="hi", voice="nova", file_prefix="/tmp/tts")

    assert cmd[:6] == ["uv", "run", "--quiet", "--project", str(mlx_tts._REPO_ROOT), "--extra"]
    assert cmd[6:12] == ["mlx", "--with", "pip", "python", "-m", "mlx_audio.tts.generate"]
    assert cmd[12:14] == ["--model", "mlx-community/Kokoro-82M-bf16"]


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


def test_speak_cli_does_not_pass_protected_params(monkeypatch, tmp_path: Path) -> None:
    """_speak_cli must strip protected keys (e.g. play) from self._params before building the CLI command."""
    binary = tmp_path / "mlx_audio.tts.generate"
    binary.write_text("binary", encoding="utf-8")
    binary.chmod(0o755)

    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    backend._service_name = "kokoro"
    backend._cli_bin = str(binary)
    backend._model_ref = "mlx-community/Kokoro-82M-bf16"
    # `play` and `audio_format` are protected; `speed` is not
    backend._params = {"play": "true", "audio_format": "mp3", "speed": "1.2"}

    captured_cmds: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        captured_cmds.append(list(cmd))
        if len(captured_cmds) == 1:
            # First call: audio generation — create the expected wav so the file check passes
            prefix_idx = cmd.index("--file_prefix") + 1
            Path(f"{cmd[prefix_idx]}.wav").write_bytes(b"RIFF" + b"\x00" * 36)
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = backend._speak_cli("hello", "nova")

    assert result is True
    cli_cmd = captured_cmds[0]
    assert "--play" not in cli_cmd, "protected key 'play' must not appear in CLI args"
    # --audio_format is set by _build_cli_command; the params loop must not add a second copy
    assert cli_cmd.count("--audio_format") == 1, "protected key 'audio_format' must not be doubled"
    assert "--speed" in cli_cmd, "non-protected key 'speed' must pass through"
    assert "1.2" in cli_cmd


def test_speak_local_does_not_pass_protected_params(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """_speak_local must not forward protected keys from self._params to generate_audio."""
    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    backend._service_name = "kokoro"
    backend._cli_bin = None
    backend._model = object()  # non-None to skip model loading
    backend._model_ref = "mlx-community/Kokoro-82M-bf16"
    # `play` and `verbose` are protected; `speed` is not
    backend._params = {"play": True, "verbose": True, "speed": 1.5}

    captured_kwargs: list[dict] = []  # type: ignore[type-arg]

    def fake_generate_audio(**kwargs):  # type: ignore[no-untyped-def]
        captured_kwargs.append(dict(kwargs))
        prefix = kwargs["file_prefix"]
        Path(f"{prefix}.wav").write_bytes(b"RIFF" + b"\x00" * 36)

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(mlx_tts, "generate_audio", fake_generate_audio)
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = backend._speak_local("hello", "nova", "kokoro")

    assert result is True
    assert len(captured_kwargs) == 1
    kwargs = captured_kwargs[0]
    assert kwargs["play"] is False, "protected key 'play' must always be forced to False"
    assert kwargs["verbose"] is False, "protected key 'verbose' must always be forced to False"
    assert kwargs["speed"] == 1.5, "non-protected key 'speed' must pass through"
