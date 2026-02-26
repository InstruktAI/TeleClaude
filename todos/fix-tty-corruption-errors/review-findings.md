# Review Findings: fix-tty-corruption-errors (Round 2)

## Review Scope

Round 2 re-review after fixes for round 1 Critical #1 and Important #1.

Commits since review baseline (`8e9d446d`):

- `e5b03bbe` — `fix(tts): guard protected CLI params in _speak_cli to prevent echo re-entry`
- `6a3c26dc` — `test(tts): add unit tests for protected param filtering in _speak_cli and _speak_local`

Files changed (full branch):

- `teleclaude/tts/backends/mlx_tts.py`
- `teleclaude/tts/backends/openai_tts.py`
- `tests/unit/test_mlx_tts_backend.py`

## Round 1 Resolution Verification

### Critical #1 — `_speak_cli` unguarded params loop: **RESOLVED**

`_speak_cli` now defines a `_protected` frozenset at line 179 and filters `self._params` through it at line 183. The protected set matches `_speak_local` exactly: `{play, verbose, model, text, voice, file_prefix, join_audio, audio_format}`. Verified: `--play` cannot re-enter the CLI command through user config.

### Important #1 — No tests for new behavior: **RESOLVED**

Two focused unit tests added to `tests/unit/test_mlx_tts_backend.py`:

- `test_speak_cli_does_not_pass_protected_params` (line 93): Verifies `--play` and `--audio_format` excluded from CLI args; non-protected `--speed` passes through.
- `test_speak_local_does_not_pass_protected_params` (line 129): Verifies `generate_audio` receives `play=False` and `verbose=False` regardless of `self._params`; non-protected `speed` passes through.

All 8 tests pass (verified: `pytest tests/unit/test_mlx_tts_backend.py` — 8 passed).

## Critical

None.

## Important

None.

## Suggestions

1. **`_protected` frozenset duplicated inline** — The same 8-key frozenset is defined independently in `_speak_cli` (line 179) and `_speak_local` (line 275). A class-level `_PROTECTED_PARAMS` constant would keep them in sync if keys change.

2. **Duplicated `afplay` playback block** (carried from round 1) — The `subprocess.run(["afplay", ...])` + error logging pattern is nearly identical in `_speak_cli` (lines 201-213) and `_speak_local` (lines 292-302). A shared `_play_audio(audio_file: Path) -> bool` helper would reduce duplication.

3. **`bug.md` documentation sections incomplete** — Investigation, Root Cause, and Fix Applied sections still contain template placeholders. The code changes and commit messages document the fix well, but the `bug.md` artifact is formally incomplete.

## Paradigm-Fit Assessment

- **Data flow:** Uses established `subprocess.run` + `tempfile.TemporaryDirectory` pattern. Audio generation → synchronous playback → cleanup. No bypass of the data layer.
- **Component reuse:** Both `_speak_cli` and `_speak_local` follow the same generate-then-play architecture with consistent error handling. The `openai_tts.py` change (`capture_output=True`) aligns with the same TTY-protection pattern.
- **Pattern consistency:** Error handling follows the codebase's `returncode → logger.error → return False` convention. Protected-param filtering uses the same frozenset idiom in both paths. Tests follow existing patterns in the file (monkeypatch, `MLXTTSBackend.__new__`, explicit assertions).
- **Copy-paste duplication:** Checked. The `afplay` block duplication is noted as a suggestion but is not a copy-paste of an existing component — it's the same author's deliberate choice to keep the two code paths self-contained.

## Why No Issues

1. **Paradigm-fit verified:** Both TTS paths (CLI and local) use the established subprocess + temp-dir pattern. No inline hacks, no data-layer bypass.
2. **Requirements met:** The bug symptom (echo/TTY corruption from async playback) is addressed by removing `--play`, adding synchronous `afplay`, filtering protected params, and adding `capture_output=True`. Verified by tracing both code paths with concrete values.
3. **Duplication checked:** The `_protected` frozenset and `afplay` block are duplicated but intentionally — noted as suggestions, not paradigm violations.

## Verdict: APPROVE
