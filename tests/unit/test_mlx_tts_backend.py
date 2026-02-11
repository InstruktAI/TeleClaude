from pathlib import Path

from teleclaude.tts.backends.mlx_tts import MLXTTSBackend


def test_resolve_cli_bin_prefers_current_env(monkeypatch, tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text("", encoding="utf-8")
    fake_cli = bin_dir / "mlx_audio.tts.generate"
    fake_cli.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_cli.chmod(0o755)

    monkeypatch.delenv("TELECLAUDE_MLX_TTS_CLI_BIN", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr("sys.executable", str(fake_python))

    backend = MLXTTSBackend.__new__(MLXTTSBackend)
    assert backend._resolve_cli_bin() == str(fake_cli)


def test_extract_cli_failure_reason_reports_missing_dependency() -> None:
    stdout = "Import error:\nMissing dependency while loading kokoro: No module named 'misaki'"
    reason = MLXTTSBackend._extract_cli_failure_reason(stdout, "")
    assert reason == "missing dependency while loading kokoro: No module named 'misaki'"


def test_resolve_cli_audio_file_uses_success_output_path(tmp_path: Path) -> None:
    audio = tmp_path / "generated.wav"
    audio.write_bytes(b"RIFF....WAVE")
    stdout = f"Audio successfully generated and saving as: {audio}"
    resolved = MLXTTSBackend._resolve_cli_audio_file(str(tmp_path), "tts_output", stdout)
    assert resolved == audio


def test_resolve_cli_audio_file_falls_back_to_expected(tmp_path: Path) -> None:
    expected = tmp_path / "tts_output.wav"
    expected.write_bytes(b"RIFF....WAVE")
    resolved = MLXTTSBackend._resolve_cli_audio_file(str(tmp_path), "tts_output", "")
    assert resolved == expected
