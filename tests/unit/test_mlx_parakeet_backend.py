"""Unit tests for MLX Parakeet STT backend CLI fallback."""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import teleclaude.stt.backends.mlx_parakeet as mlx_parakeet
from teleclaude.stt.backends.mlx_parakeet import MLXParakeetBackend


def _make_backend() -> MLXParakeetBackend:
    backend = MLXParakeetBackend.__new__(MLXParakeetBackend)
    backend._cli_bin = "/tmp/mlx_audio.stt.generate"
    backend._model_ref = "mlx-community/parakeet-tdt-0.6b-v3"
    backend._model = None
    return backend


def test_ensure_model_cli_only_does_not_import_mlx_audio():
    """When CLI backend exists, mlx_audio import must not be attempted."""
    backend = _make_backend()

    with patch.object(mlx_parakeet, "import_module", side_effect=AssertionError("should not import mlx_audio")):
        assert backend._ensure_model() is True


def test_transcribe_cli_passes_output_path_and_reads_json_file():
    """CLI fallback must pass --output-path and parse result from that file."""
    backend = _make_backend()

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as audio_file:
        audio_file.write(b"fake audio")
        audio_path = audio_file.name

    try:
        seen_cmd: list[str] = []

        def _fake_run(cmd, check, capture_output, text):  # noqa: ANN001
            nonlocal seen_cmd
            seen_cmd = list(cmd)
            out_idx = seen_cmd.index("--output-path")
            output_path = seen_cmd[out_idx + 1]
            Path(output_path).write_text('{"text":"hello from cli"}', encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=_fake_run):
            text = backend._transcribe_cli(audio_path, language="en")

        assert text == "hello from cli"
        assert "--output-path" in seen_cmd
        assert "--format" in seen_cmd
        assert "json" in seen_cmd
        assert "--language" in seen_cmd
        assert "en" in seen_cmd
    finally:
        Path(audio_path).unlink(missing_ok=True)


def test_transcribe_cli_falls_back_to_stdout_when_output_file_missing():
    """If CLI does not write the file, parser should still use stdout JSON."""
    backend = _make_backend()

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as audio_file:
        audio_file.write(b"fake audio")
        audio_path = audio_file.name

    try:

        def _fake_run(_cmd, check, capture_output, text):  # noqa: ANN001
            return SimpleNamespace(returncode=0, stdout='{"text":"stdout fallback"}', stderr="")

        with patch("subprocess.run", side_effect=_fake_run):
            text = backend._transcribe_cli(audio_path)

        assert text == "stdout fallback"
    finally:
        Path(audio_path).unlink(missing_ok=True)


def test_transcribe_cli_raises_when_cli_returns_error():
    """CLI non-zero exit should raise a clear RuntimeError."""
    backend = _make_backend()

    with tempfile.NamedTemporaryFile(mode="wb", suffix=".ogg", delete=False) as audio_file:
        audio_file.write(b"fake audio")
        audio_path = audio_file.name

    try:

        def _fake_run(_cmd, check, capture_output, text):  # noqa: ANN001
            return SimpleNamespace(returncode=2, stdout="", stderr="missing output path")

        with patch("subprocess.run", side_effect=_fake_run):
            try:
                backend._transcribe_cli(audio_path)
                assert False, "expected RuntimeError"
            except RuntimeError as exc:
                assert "Parakeet CLI failed" in str(exc)
                assert "missing output path" in str(exc)
    finally:
        Path(audio_path).unlink(missing_ok=True)
