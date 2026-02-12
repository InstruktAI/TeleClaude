# REVIEW FINDINGS: help-desk

## Critical

- None.

## Important

- `teleclaude/core/command_handlers.py:380` — `list_sessions()` constructs `SessionSummary` without `human_email` and `human_role`, even though the model/DTO now include them. This violates the requirement that session summaries expose identity fields and causes role/identity data to be dropped in list responses.  
  Evidence path: `db.list_sessions()` returns sessions with these fields (`teleclaude/core/db.py:103`), but the mapper in `list_sessions()` does not forward them.

## Suggestions

- `teleclaude/mcp/role_tools.py:1` — Module docstring still says filtering applies only when `role == worker`, but filtering now also depends on human-role/session context. Update comments to match behavior to prevent future review confusion.

## Fixes Applied

- Issue: `teleclaude/core/command_handlers.py:380` dropped `human_email` and `human_role` while building `SessionSummary`.
  Fix: Forwarded `s.human_email` and `s.human_role` in `list_sessions()`, and extended `tests/unit/test_command_handlers.py` list-sessions unit coverage to assert identity fields are preserved.
  Commit: `febc489d`

## Verdict

REQUEST CHANGES
