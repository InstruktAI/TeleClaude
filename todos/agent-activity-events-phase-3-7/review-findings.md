# Review Findings: agent-activity-events-phase-3-7

## Summary

Rename of event vocabulary (`after_model`/`agent_output` → `tool_use`/`tool_done`) and DB columns is mechanically correct and comprehensive. New tests cover event emission and broadcast paths well. All findings from round 1 have been resolved.

## Round 1 Findings (all resolved)

### 1. `tool_name` coercion produces `"None"` string when absent (Important)

**Fixed in:** fac0e656

- Guarded `str()` call to prevent `str(None)` when tool_name/toolName keys are absent
- Now returns `None` instead of the literal string `"None"`

### 2. Stale comments in receiver still reference old vocabulary (Suggestion)

**Fixed in:** 75f9ec33

- Updated comment on line 688: `'tool_use' -> 'ToolUse'`
- Updated comment on line 694: `for direct events like 'tool_done'`

## Round 2 Verification

- All round 1 findings confirmed fixed by code inspection
- `make test`: 73 passed, 0 failed
- `make lint`: ruff format, ruff check, pyright all clean
- Grep for stale references (`after_model`/`agent_output`/`AFTER_MODEL`/`AGENT_OUTPUT`) in production code: only migration files and legitimate function names (e.g., `render_agent_output`, `summarize_agent_output`) which describe output-as-concept, not event vocabulary
- All implementation-plan tasks checked `[x]`
- No deferrals
- Documentation updated across 5 doc files
- New test files: `test_agent_activity_events.py` (5 tests), `test_agent_activity_broadcast.py` (7 tests)

## Critical

None.

## Important

None.

## Suggestions

None.

## Verdict: APPROVE
