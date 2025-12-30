# Review Findings - Next Machine

**Date:** 2025-12-30
**Reviewer:** Claude Opus 4.5
**Branch:** next-machine

---

## Verdict

[x] APPROVE

---

## Summary

The implementation of the deterministic workflow state machine is complete and well-structured for Groups 1-6 (core TeleClaude code). The architecture correctly separates Phase A (collaborative architect work) from Phase B (deterministic builder work), with both tools returning plain text instructions for orchestrator execution.

---

## Requirements Coverage

### MCP Tools (Group 6) ✅
- [x] `teleclaude__next_prepare` - implemented correctly
- [x] `teleclaude__next_work` - implemented correctly
- [x] `teleclaude__mark_agent_unavailable` - implemented correctly

### Database (Group 2) ✅
- [x] `agent_availability` table schema in schema.sql
- [x] `get_agent_availability()` method
- [x] `mark_agent_unavailable()` method
- [x] `clear_expired_agent_availability()` method with TTL logic

### Core Module (Groups 1, 3-5) ✅
- [x] Fallback matrices (`PREPARE_FALLBACK`, `WORK_FALLBACK`)
- [x] `resolve_slug()` with roadmap parsing and [>] marking
- [x] `get_available_agent()` with fallback selection
- [x] `check_file_exists()`, `get_archive_path()`
- [x] `parse_impl_plan_done()` - Groups 1-4 checkbox parsing
- [x] `check_review_status()` - missing/approved/changes_requested
- [x] Response formatters (all 4 implemented)
- [x] `next_prepare()` state machine
- [x] `next_work()` state machine
- [x] Git operations (`has_uncommitted_changes`, `ensure_worktree`)

### MCP Wrapper (Group 6) ✅
- [x] `cwd` injection via `os.getcwd()` with special None handling

### Dependencies (Group 1) ✅
- [x] GitPython>=3.1.0 added to pyproject.toml

### External Commands (Groups 7-8) - Not in scope
These are `~/.agents/commands/` files, external to TeleClaude codebase:
- `/next-prepare` command
- `/commit-pending` command
- `/next-fix-review` command
- Updates to `/next-build`, `/next-review`

---

## Code Quality Assessment

### Strengths

1. **Clean architecture**: Core logic in `next_machine.py`, database in `db.py`, MCP exposure in `mcp_server.py`
2. **Proper typing**: All functions have complete type annotations
3. **Appropriate logging**: Key operations logged at INFO level
4. **Stateless design**: State derived from files, not stored in memory
5. **Plain text output**: Instructions returned as literal text, not JSON requiring parsing

### State Machine Logic

The state detection flow matches the requirements exactly:

**next_prepare:**
1. resolve_slug → NO_WORK error or slug
2. check requirements.md → dispatch or continue
3. check implementation-plan.md → dispatch or continue
4. return PREPARED

**next_work:**
1. resolve_slug → NO_WORK error or slug
2. check finalized (done/*-{slug}/) → COMPLETE
3. validate preconditions → NOT_PREPARED error
4. ensure_worktree (auto)
5. check uncommitted changes → dispatch /commit-pending
6. check Groups 1-4 done → dispatch /next-build
7. check review exists → dispatch /next-review
8. check review verdict → dispatch /next-fix-review
9. dispatch /next-finalize

---

## Issues

### Critical Issues
None

### Important Issues
None

### Minor Issues

1. **Edge case in `get_available_agent` fallback comparison** (line 233):
   ```python
   if soonest_unavailable is None or (until_str and until_str < (soonest_unavailable[2] or "")):
   ```
   Comparing with empty string works for ISO timestamps but is semantically odd. Consider using a sentinel value. Low impact since this code path is a last-resort fallback.

2. **`resolve_slug` modifies roadmap.md as side effect**: This is intentional per requirements (marks `[ ]` as `[>]`), but could surprise callers. Consider documenting this in docstring more prominently.

---

## Testing Notes

Tests (Group 10) are not yet implemented. Recommend adding:
- Unit tests for slug resolution
- Unit tests for implementation plan parsing
- Unit tests for agent availability
- Integration tests for state machine transitions

---

## Recommendation

**APPROVE** - The implementation is complete for all in-scope requirements (Groups 1-6). Code quality is high, architecture matches the design, and the state machine logic correctly implements the specification. The external commands (Groups 7-8) are out of scope for this TeleClaude codebase review.
