# Bug: telec sessions end does not support 'self' as a session_id alias. Agents must use the incantation cat $TMPDIR/teleclaude_session_id to discover their own session ID before they can end themselves. Add 'self' resolution to telec sessions end ONLY — no other subcommand needs it. When session_id is 'self', resolve it to the contents of $TMPDIR/teleclaude_session_id. Update the -h output for the end subcommand to document 'self' as a valid value. The telec-cli spec baseline already auto-propagates via @exec: telec sessions -h, so no separate doc work is needed once the CLI is updated.

## Symptom

telec sessions end does not support 'self' as a session_id alias. Agents must use the incantation cat $TMPDIR/teleclaude_session_id to discover their own session ID before they can end themselves. Add 'self' resolution to telec sessions end ONLY — no other subcommand needs it. When session_id is 'self', resolve it to the contents of $TMPDIR/teleclaude_session_id. Update the -h output for the end subcommand to document 'self' as a valid value. The telec-cli spec baseline already auto-propagates via @exec: telec sessions -h, so no separate doc work is needed once the CLI is updated.

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-02

## Investigation

`handle_sessions_end` in `teleclaude/cli/tool_commands.py` accepts `session_id` as a positional arg or via `--session`/`-s`, but has no special-case handling for any alias values.

`_read_caller_session_id()` already exists in `teleclaude/cli/tool_client.py` — it reads `$TMPDIR/teleclaude_session_id` and returns the session ID string or `None`.

## Root Cause

No alias resolution was implemented for `session_id` in `handle_sessions_end`. The handler passes the raw value straight to the DELETE API call.

## Fix Applied

- Imported `_read_caller_session_id` from `tool_client` into `tool_commands`.
- After argument parsing in `handle_sessions_end`, added a check: if `session_id == "self"`, resolve it via `_read_caller_session_id()`. If resolution fails (file not found), exit with a clear error.
- Updated the docstring (which serves as `-h` output) to document `self` as a valid value with an example.
- Added 3 unit tests: self-resolves, self-fails-gracefully, literal-id-unchanged.
