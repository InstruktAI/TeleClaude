# Review Findings: fix-tty-corruption-errors

## Critical

1. **`_speak_cli` does not filter protected params — re-enables the echo bug via config** (`teleclaude/tts/backends/mlx_tts.py:175-177`)

   `_speak_local` correctly guards against user params overriding internally-controlled keys (`play`, `verbose`, `model`, `text`, `voice`, `file_prefix`, `join_audio`, `audio_format`) using a `_protected` frozenset. However, `_speak_cli` passes **all** `self._params` as CLI flags without any filtering:

   ```python
   # Pass config params as CLI flags
   for key, val in self._params.items():
       cmd.extend([f"--{key}", str(val)])
   ```

   If a service config includes `play: true`, this re-adds `--play` to the CLI command, causing the exact async-playback race that this fix removes by deleting `--play` from `_build_cli_command`. Similarly, keys like `--model`, `--text`, `--voice`, `--file_prefix` would be passed twice (once from `_build_cli_command`, once from the loop), potentially overriding the intended temp-dir prefix or voice.

   **Fix:** Apply the same `_protected` filtering pattern used in `_speak_local` to the CLI params loop.

## Important

1. **No tests for the new behavior** — No tests were added covering:
   - The synchronous `afplay` call added to `_speak_cli` (lines 194-206)
   - The `_protected` keys guard in `_speak_local` (lines 268-271)
   - The `capture_output=True` change in `openai_tts.py`

   The existing `test_mlx_tts_backend.py` only covers `_resolve_cli_bin`, `_ensure_model`, and `_build_cli_command`. The new playback and param-guarding behaviors are untested. At minimum, a unit test should verify that `_speak_local` and `_speak_cli` do not pass protected keys from `self._params` to the CLI or `generate_audio`.

## Suggestions

1. **Duplicated `afplay` playback block** — The `afplay` subprocess call + error handling pattern is nearly identical in `_speak_cli` (lines 194-206) and `_speak_local` (lines 285-295). Consider extracting a shared `_play_audio(audio_file: Path) -> bool` helper to reduce duplication.

2. **`bug.md` Investigation/Root Cause sections populated only in the diff, not in the working tree** — The committed `bug.md` on the branch has complete investigation and fix-applied sections, but the working tree copy still shows the template placeholders. This is cosmetic if the committed version is correct, but the working tree file should match.

## Paradigm-Fit Assessment

- **Data flow:** Consistent — uses established `subprocess.run` + `tempfile.TemporaryDirectory` pattern for audio generation and playback; logging through the project's structured logger.
- **Component reuse:** The `afplay` call mirrors the existing pattern in `_speak_local`, maintaining consistency.
- **Pattern consistency:** Error handling follows the established `returncode` → `logger.error` → `return False` pattern throughout the file.

## Verdict: REQUEST CHANGES

The critical finding means the fix is incomplete for the CLI path — the same config-override vulnerability it closes in `_speak_local` remains open in `_speak_cli`.
