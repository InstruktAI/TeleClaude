# Daemon Restart Discipline Gap — Idea

## Summary

Memory ID 25 states: "Always restart daemon after code changes." This is a working practice that prevents stale agent state, but it's inconsistently applied.

## Current State

- **Documented**: Captured in memory as a friction point
- **Not enforced**: No automation or hooks ensure it happens
- **Context-dependent**: Whether a restart is needed depends on which files changed, but agents lack that visibility

## Pattern

This is part of a broader pattern of **working practices that are known to the team but not automated**:

- Commit without asking (ID 19)
- Bug hunting philosophy (ID 11)
- Five-minute execution threshold (ID 10)

These are behavioral patterns, not code patterns. They live in memory because they shape how agents work together.

## Actionable Insights

1. **Daemon health check**: After agent code changes, add a pre-commit hook that validates daemon is still alive OR add a telemetry signal to detect crashes.

2. **Working practice enforcement**: Consider a TUI feature that flags code changes affecting core systems and suggests `make restart`.

3. **Session lifecycle spec**: ID 30 says "end_session is mandatory" — this suggests the same discipline applies to cleanup. Codify the session lifecycle.

## Next Steps

- Document the daemon restart discipline in a formal procedure
- Add telemetry to detect crash-and-restart cycles
- Create a pre-commit guard for code that requires daemon restart

## Related Memories

- ID 25: Always restart daemon after code changes
- ID 30: end_session is mandatory — never assume session is gone
- ID 19: Checkpoint: commit without asking
