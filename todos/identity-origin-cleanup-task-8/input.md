# Task 8: Refactor daemon headless session creation via command pipeline

## Context

`teleclaude/daemon_hook_outbox.py` currently calls `db.create_headless_session()` directly. This bypasses the command service and diverges from the session creation path used elsewhere (which routes through CreateSessionCommand).

## Scope

- Identify all headless session creation calls in daemon_hook_outbox.py
- Replace direct DB calls with CreateSessionCommand through command service
- Verify session creation path is uniform across all callers
- Update tests to reflect new path

## Success Criteria

- All daemon headless sessions are created via CreateSessionCommand
- Command pipeline is used consistently for all session creation
- Session creation path is centralized and auditable
- Tests verify command path is invoked
- No regressions in daemon session creation
