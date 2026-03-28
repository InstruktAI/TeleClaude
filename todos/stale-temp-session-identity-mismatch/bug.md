# Bug: stale temp session identity causes session identity mismatch in tc_tui

## Symptom

stale temp session identity causes session identity mismatch in tc_tui

## Detail

Summary
- telec CLI requests fail with `permission denied — session identity mismatch` when the shell is in `tc_tui` but TMPDIR/TMP/TEMP still point at a closed session temp dir containing `teleclaude_identity.json`.
- This blocks normal orchestrator commands like `telec todo work <slug>` and `telec sessions tail <session>` even though the daemon is healthy and terminal login is available.

Concrete reproduction from current environment
- `TMPDIR=/Users/Morriz/.teleclaude/tmp/sessions/6ee1185e-aff9-4c64-b28e-2a2d0bbc10af`
- `TMP=/Users/Morriz/.teleclaude/tmp/sessions/6ee1185e-aff9-4c64-b28e-2a2d0bbc10af`
- `TEMP=/Users/Morriz/.teleclaude/tmp/sessions/6ee1185e-aff9-4c64-b28e-2a2d0bbc10af`
- `teleclaude_identity.json` in that dir contains `{"human_role": "admin", "session_id": "6ee1185e-aff9-4c64-b28e-2a2d0bbc10af"}`
- `tmux display-message -p "#S"` returns `tc_tui`
- Plain call fails: `telec todo work activation-trigger` -> `Error: permission denied — session identity mismatch`
- Plain tail fails similarly.
- Clearing all temp env vars makes the same calls work: `env -u TMPDIR -u TMP -u TEMP telec todo work activation-trigger` returns the state-machine instruction block, and `env -u TMPDIR -u TMP -u TEMP telec sessions tail c1fa8de4-b436-4049-8b56-332270f61efa --tools --thinking` succeeds.

Observed lifecycle evidence
- Session `6ee1185e-aff9-4c64-b28e-2a2d0bbc10af` was created with tmux session `tc_6ee1185e-aff9-4c64-b28e-2a2d0bbc10af` and later closed (`DELETE /sessions/6ee...`, `Killed tmux session tc_6ee...`, `Closed session 6ee... in database`).
- After that, the shell still retained TMPDIR/TMP/TEMP pointing at the closed session temp dir while current tmux session was `tc_tui`.

Code path
- `teleclaude/cli/tool_client.py` always reads `session_id` from `teleclaude/session_identity.py`, which resolves identity from the first available temp env among TMPDIR/TMP/TEMP.
- The same client also always sends `x-tmux-session` from `tmux display-message -p "#S"`.
- `teleclaude/api/auth.py::_verify_session_identity()` loads the session row and raises `403 session identity mismatch` when `x_tmux_session` differs from `session.tmux_session_name`.
- `teleclaude/core/db/_sessions.py::get_session()` returns stored sessions regardless of `closed_at`, so stale identity files for closed sessions can still reach the tmux-mismatch branch instead of being treated as stale/unknown.

Likely root cause
- TeleClaude sets TMPDIR/TMP/TEMP to a per-session temp dir when creating tmux-backed sessions, but there is no reliable cleanup/rebind when the shell returns to `tc_tui` or when a session is closed.
- As a result, later CLI calls from `tc_tui` present a stale `x-caller-session-id` from a closed session together with `x-tmux-session=tc_tui`, which the daemon correctly rejects.

Impact
- Orchestrator and operator commands become unusable from a shell that has stale temp env vars.
- Error message is misleading because the deeper issue is stale closed-session identity, not an operator attempting to forge identity.

Fix surfaces to investigate
- Clear or rebind TMPDIR/TMP/TEMP when leaving/closing a session or when returning to `tc_tui`.
- In `tool_client` / `session_identity`, ignore file-based session identity when current tmux session is `tc_tui` or when the resolved session is closed/stale.
- In auth, consider rejecting closed sessions before tmux cross-check so stale identity returns a clearer stale/unknown-session error instead of 403 mismatch.

Requested outcome
- Restore reliable `telec` CLI operation from `tc_tui` after sessions close, without requiring users to manually unset TMPDIR/TMP/TEMP.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-28

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
