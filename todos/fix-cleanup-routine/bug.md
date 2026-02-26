# Bug:

## Symptom

`telec list --closed` shows sessions older than 3 days:

f6067144-c181-4504-a1d1-307a628a2c89 MozBook: claude/med (6d ago, closed 6d ago)

I wonder how this is possible. We have a 72 hour cleanup routine. Why does this not get cleaned up?

## Discovery Context

Reported by: manual
Session: none
Date: 2026-02-24

## Investigation

Traced the 72h cleanup routine in `teleclaude/services/maintenance_service.py::_cleanup_inactive_sessions()`.

The method iterates all sessions (including closed) and has two branches:

1. Sessions with `closed_at` set → normalizes `lifecycle_status` to "closed", then `continue` (skips entirely)
2. Active sessions with `last_activity` older than 72h → terminates (closes) them via `terminate_session`

Neither branch deletes closed sessions from the database. Branch 1 skips them; branch 2 only closes active sessions (doesn't delete).

## Root Cause

In `_cleanup_inactive_sessions()`, sessions with `closed_at` set are unconditionally skipped after lifecycle normalization (line 182-187). The 72h cutoff check on line 189 only evaluates active sessions. There is no code path that purges old closed sessions from the database, so they accumulate indefinitely.

## Fix Applied

Added a purge step in the `closed_at` branch of `_cleanup_inactive_sessions()`: when a closed session's `closed_at` timestamp is older than the 72h cutoff, it is deleted from the database via `terminate_session()` with `delete_db=True` and `kill_tmux=False` (tmux is long gone for these sessions).

Files changed:

- `teleclaude/services/maintenance_service.py` — added purge logic for old closed sessions
- `tests/unit/test_daemon.py` — added `test_cleanup_purges_closed_sessions_older_than_72h`
