# Bug:

## Symptom

Whenever the daemon starts up the integrator, that session immediately takes focus. But that should not happen. Non-human initiated sessions are not to be interpreted as to have focus. Only headless sessions may take focus when they are adopted by the user. Or new sessions that are started by the user may take focus. There are some other paths that should also take focus which are the other scenarios that start a session by the user by the human which is from the to-do pane where we can start a session with the letter S or prepare a to do with the letter P, which starts an agent in the next prepare routine. Also the letter R or refining starts an agent session with a preset command. Stuff like that. Those three should also be listened for and taking focus. Potentially those have different event names when they come in via the web socket. So analyze.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-18

## Investigation

Traced the session focus path from daemon startup through WebSocket to TUI:

1. Daemon spawns integrator via `spawn_integrator_session()` → `run_slash_command(detach=True)`
2. `run_slash_command` creates a session with `initiator_session_id=None` (no parent session exists)
   but WITH `session_metadata` containing `system_role="integrator"` and `job="integrator"`
3. SESSION_STARTED event reaches TUI via WebSocket
4. `on_session_started()` in `app_ws.py` checks `if not session.initiator_session_id` to decide
   whether to auto-focus — since integrator has no initiator, it passes this check
5. The session gets auto-selected with `request_focus=True`, stealing focus

User-initiated sessions (from TUI modal via S/P/R keys or new session) also have
`initiator_session_id=None` but do NOT have `session_metadata.job` set. This is the
discriminating signal.

## Root Cause

`on_session_started()` in `teleclaude/cli/tui/app_ws.py:221` uses `initiator_session_id`
as the sole discriminator for user-initiated vs daemon-spawned sessions. Daemon-spawned
sessions via `run_slash_command` have no initiator (since there's no parent session) but
carry `session_metadata.job` — a signal the focus logic did not check.

## Fix Applied (v2 — after review)

Replaced metadata-based heuristic with TUI-side session tracking. The original fix
checked `session_metadata.job` to identify daemon-spawned sessions, but user-initiated
run-session flows also set `job` via `_prepare_run_session`, causing those sessions
to incorrectly skip auto-focus.

**New approach:** The TUI tracks session IDs it creates in `_tui_initiated_sessions`.
`on_create_session_request` adds the returned `session_id` after successful creation.
`on_session_started` auto-focuses only if the session_id is in the tracking set,
then removes it. This is correct by construction — no metadata heuristics needed.

Changed files:

- `teleclaude/cli/tui/app.py` — added `tui_initiated_sessions: set[str]` to `_AppRuntimeState`
- `teleclaude/cli/tui/app_actions.py` — track session IDs after successful create/revive/resume
- `teleclaude/cli/tui/app_ws.py` — replaced `is_daemon_spawned` check with set membership

Test file: `tests/unit/cli/tui/test_app_ws.py` — three tests:

- `test_on_session_started_daemon_spawned_session_does_not_auto_focus` (not in tracking set)
- `test_on_session_started_user_initiated_session_auto_focuses` (in tracking set, gets focus)
- `test_on_session_started_user_run_session_with_job_auto_focuses` (has job metadata BUT is TUI-tracked)
