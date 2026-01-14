# Code Review: test-cleanup

**Reviewed**: January 14, 2026
**Reviewer**: Codex

## Completeness Verification

### Implementation Plan Status
- Unchecked tasks: 0
- Silent deferrals found: no

### Success Criteria Verification

| Criterion | Implemented | Call Path | Test | Status |
|-----------|-------------|-----------|------|--------|
| Production code is sacrosanct | N/A - tests only diff | N/A | N/A | ✅ |
| Tests are black box (public interface only) | `tests/unit/test_sessions_view.py:59` | test -> private method | `test_update_activity_state_marks_idle_when_activity_is_old` | ❌ |
| Tests verify behavior over internal calls | `tests/unit/test_command_handlers.py` | pytest -> test -> public handler | `test_handle_new_session_creates_db_session` | ✅ |
| Independence (no shared mutable state) | `tests/unit/test_db.py:12` | pytest fixture -> isolated db | `test_create_session_minimal` | ✅ |
| Determinism (time, randomness controlled) | `tests/unit/test_sessions_view.py:59` | pytest -> patched datetime | `test_update_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Speed (<100ms per unit) | NOT VERIFIED | NOT VERIFIED | NOT VERIFIED | ❌ |
| Clarity (naming and docstrings) | `tests/unit/test_pane_manager.py:1` | pytest -> docstringed test | `test_toggle_session_returns_false_when_not_in_tmux` | ✅ |
| Single responsibility (one behavior per test) | `tests/unit/test_pane_manager.py:31` | pytest -> single outcome | `test_show_session_tracks_parent_and_child_panes` | ✅ |

**Verification notes:**
- The black box criterion is violated by direct calls to private methods in several new tests.
- Speed was not measured in this review; no timing assertions or benchmarks present.

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_session_lifecycle.py`
- Coverage: session create -> terminate -> tmux cleanup -> db deletion
- Quality: uses real db and cleanup flow with mocked tmux boundary

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Do not test private methods | ❌ | Direct calls to `_update_activity_state`, `_toggle_session_pane`, `_launch_session_split`, `_extract_tmux_session_name`.
| No loops or conditionals in tests | ⚠️ | `tests/integration/test_feedback_cleanup.py` uses a loop to collect deleted ids.
| Docstrings for every test | ✅ | Added across new and edited files.
| Mock only at system boundaries | ⚠️ | Some tests patch internal methods in addition to boundary calls.
| Add Priority 0 coverage (pane manager, sessions view, preparation view, mcp handler) | ✅ | New test files added for each component.

## Critical Issues (must fix)

- None.

## Important Issues (should fix)

- [tests] `tests/unit/test_sessions_view.py:59` - Tests call private methods (`_update_activity_state`, `_toggle_session_pane`) which violates the black box requirement and the "Do NOT test private methods" rule.
  - Suggested fix: Exercise behavior through public APIs (e.g., drive `SessionsView` via public render or event entry points) and validate observable state changes.
- [tests] `tests/unit/test_preparation_view.py:65` - Tests call private method `_launch_session_split` directly.
  - Suggested fix: Trigger session launch via the public view action that calls it, then assert screen and tmux side effects.
- [tests] `tests/unit/test_mcp_handlers.py:33` - Tests call private helper `_extract_tmux_session_name` directly instead of testing via a public MCP handler path.
  - Suggested fix: Cover this logic through a public handler test that exercises the same parsing flow.
- [tests] `tests/integration/test_feedback_cleanup.py:71` - Test logic uses explicit loop and conditionals to validate deletes, violating the "no loops or conditionals in tests" requirement.
  - Suggested fix: Use `assert_has_calls` with explicit expected calls to avoid custom iteration logic.
- [lint] `tests/integration/test_mcp_tools.py:3` - Unused import `asyncio` will fail linting rules.
  - Suggested fix: Remove the unused import.

## Suggestions (nice to have)

- [tests] `tests/unit/test_pane_manager.py:14` - Consider adding an outcome assertion for the returned pane id when `_run_tmux` returns a concrete id to better demonstrate observable behavior.

## Strengths

- Added Priority 0 coverage for previously untested TUI components and MCP handler helpers.
- Integration fixture now isolates REST socket paths to avoid collisions in parallel runs.
- Docstrings and naming consistency improved across many test files.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Replace direct calls to private methods with tests that exercise public interfaces.
2. Remove unused `asyncio` import from `tests/integration/test_mcp_tools.py`.
3. Remove loop-based validation in `tests/integration/test_feedback_cleanup.py` to align with test structure rules.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| `tests/unit/test_sessions_view.py:59` | Refactored to use public `refresh` and `handle_enter` APIs. | `e4c4e47` |
| `tests/unit/test_preparation_view.py:65` | Refactored to use public `handle_enter` and `handle_key` actions. | `f6a1c54` |
| `tests/unit/test_mcp_handlers.py:33` | Refactored to test via public `teleclaude__start_session` API. | `86189ea` |
| `tests/integration/test_feedback_cleanup.py:71` | Replaced loop with explicit `assert_has_calls` using `unittest.mock.call`. | `266780b` |
| `tests/integration/test_mcp_tools.py:3` | Removed unused `asyncio` import. | `c992bd2` |
| `tests/unit/test_pane_manager.py:31` | Fixed `TypeError` by adding missing `is_local` argument. | `ce8a66a` |
