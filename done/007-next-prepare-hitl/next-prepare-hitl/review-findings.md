# Code Review: next-prepare-hitl

## Review Summary

[x] APPROVE

## Changes Reviewed

1. **HITL parameter added** - `next_prepare()` now accepts `hitl: bool = True` parameter
2. **Interactive guidance** - Returns comprehensive guidance for calling AI when HITL=true
3. **Autonomous dispatch** - Dispatches to worker AI when HITL=false
4. **Removed wrong phase logic** - `is_in_progress` check removed (belongs in `next_work`)
5. **Worktree context fix** - State machine now checks files in worktree after `ensure_worktree()`
6. **Orchestration guidance** - Added principle to `format_tool_call()` to prevent micromanaging

## Test Coverage

- 5 new unit tests added for HITL functionality
- All 477 unit tests pass
- Lint passes with no errors

## Manual Verification

- Daemon restarts successfully
- `next_prepare()` returns correct guidance for HITL=true mode
- `next_prepare()` dispatches correctly for HITL=false mode
- Worktree file checks work correctly

## Notes

The worktree context fix was added during implementation after discovering that
the state machine was checking files in main repo instead of worktree.
