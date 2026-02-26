# Bug:

## Symptom

TTS is flaky and seems in a corrupt state leading to all voices ending with echos.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-26

## Investigation

Traced TTS flow through `queue_runner.py` → `MLXTTSBackend._speak_cli` / `_speak_local` → audio playback.

Three concrete issues identified:

1. **`_speak_cli` async-playback race**: The CLI command includes `--play`, which lets the mlx_audio CLI play the audio file. If the CLI spawns `afplay` (or another player) asynchronously and exits immediately, `subprocess.run` returns while audio is still playing. The exclusive file lock in `run_tts_with_lock` is then released, allowing the next TTS request to start while previous audio is still active → two streams play simultaneously → echo.

2. **`openai_tts.py` missing `capture_output`**: `afplay` is invoked via `subprocess.run` without `capture_output=True`. Any error output from `afplay` is written directly to the daemon's stdout/stderr, which may be the TUI terminal → TTY corruption.

3. **`_speak_local` does not guard internally-controlled kwargs**: `generate_kwargs.update(self._params)` allows service-level config params to override `play=False` and `verbose=False`. If a config had `play: true`, `generate_audio()` would play the audio AND `afplay` would play it again → double-play. If `verbose: true`, `generate_audio()` would write progress output to the daemon's TTY → corruption.

## Root Cause

The file lock in `run_tts_with_lock` only serializes the _initiation_ of TTS calls — it does not guarantee that audio playback has finished before the lock is released. In `_speak_cli`, playback is delegated to the CLI via `--play`. If the CLI exits before playback completes (async audio spawn), the lock is released prematurely, enabling overlapping audio across consecutive TTS events → persistent echo artifacts.

Secondary: `openai_tts.py` exposes `afplay` output to the daemon TTY, causing intermittent display corruption.

Tertiary: `_speak_local` allows critical internal kwargs (`play`, `verbose`) to be clobbered by user-supplied service params.

## Fix Applied

1. **`mlx_tts._build_cli_command`**: Removed `--play` from `cli_args` so the CLI only generates the audio file.
2. **`mlx_tts._speak_cli`**: Added an explicit `afplay` call inside the `with tempfile.TemporaryDirectory()` context, mirroring `_speak_local`. Audio playback is now synchronous and the lock is held for the full playback duration.
3. **`openai_tts.py`**: Added `capture_output=True` to the `afplay` call to prevent error output from reaching the daemon TTY.
4. **`mlx_tts._speak_local`**: Protected `play`, `verbose`, `model`, `text`, `voice`, `file_prefix`, `join_audio`, and `audio_format` from being overridden by `self._params`.
