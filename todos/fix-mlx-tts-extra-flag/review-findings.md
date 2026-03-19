# Review Findings: fix-mlx-tts-extra-flag

**Ad-hoc review (via from-main)** — scope and demo lanes skipped per procedure.

## Summary

Single-file change: removes `--extra mlx --with pip` from the `uv run` command in
`MLXTTSBackend._build_cli_command()`. The flags are obsolete because `mlx-audio` was
promoted from an optional extra to a platform-conditional regular dependency in
`pyproject.toml`.

## Lane: Code

No issues. The removal is clean — the remaining `uv run --quiet --project {root}
python -m mlx_audio.tts.generate ...` command is well-formed. No logic changes,
no new branches, no modified control flow.

## Lane: Paradigm

No issues. The change follows the existing pattern — `_build_cli_command` constructs
a list of CLI args, and the removal keeps the structure consistent.

## Lane: Principles

No issues. No new fallbacks, no coupling changes, no responsibility shifts. Pure
removal of stale flags.

## Lane: Security

No issues. No secrets, no new subprocess invocations. The existing `subprocess.run`
with list-based args (not shell=True) remains safe against command injection.

## Lane: Tests

No issues introduced. The existing test file (`tests/unit/tts/backends/test_mlx_tts.py`)
contains characterization tests that mock `_speak_cli` and `_speak_local` — they don't
test `_build_cli_command` output directly. This is a pre-existing coverage gap, not
introduced by this change. The removed flags are a `uv` concern (package resolution),
not observable behavior at the `speak()` boundary.

## Lane: Errors (Silent Failure Hunt)

No issues introduced. The existing broad exception catches in `_ensure_model` and
`speak` are pre-existing. The change does not add or modify error handling.

## Lane: Comments

No issues. No comments were added, modified, or made stale by this change.

## Lane: Logging

No issues. No logging statements changed.

## Lane: Simplify

Not applicable — no simplification opportunities in a 4-line removal.

---

## Unresolved Findings

**Critical:** 0
**Important:** 0

## Why No Issues

1. **Paradigm-fit:** Verified against adjacent `_build_cli_command` structure — list-based
   arg construction pattern preserved.
2. **Requirements met:** The single requirement ("Remove --extra mlx from uv run CLI
   fallback") is directly satisfied by the diff.
3. **Duplication:** No copy-paste; single call site for the removed flags.
4. **Security:** Subprocess invocation uses list args (no shell injection surface).
   No secrets or credentials in the diff.
5. **Correctness:** Confirmed `mlx-audio` is a regular dep in `pyproject.toml`
   (`"mlx-audio; sys_platform == 'darwin' and platform_machine == 'arm64'"`),
   making `--extra mlx` invalid.

## Verdict: APPROVE
