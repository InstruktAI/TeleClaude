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
| Production code is sacrosanct | N/A — tests-only diff | N/A | N/A | ✅ |
| Pane manager coverage (show, hide, toggle) | `tests/unit/test_pane_manager.py:9` | pytest → TmuxPaneManager.show_session/toggle_session/hide_sessions | `test_show_session_tracks_parent_and_child_panes` | ✅ |
| SessionsView idle tracking via public refresh | `tests/unit/test_sessions_view.py:39` | pytest → SessionsView.refresh → _update_activity_state | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| PreparationView session launch via public handle_enter | `tests/unit/test_preparation_view.py:52` | pytest → PreparationView.handle_enter → session_launcher.attach_tmux_session | `test_handle_enter_on_ready_todo_splits_tmux_in_tmux_env` | ✅ |
| Deterministic config isolation | `tests/unit/test_preparation_view.py:11` | import → config load | NO TEST | ❌ |

**Verification notes:**
- `tests/unit/test_preparation_view.py` and `tests/unit/test_mcp_handlers.py` import config-backed modules without setting `TELECLAUDE_CONFIG_PATH`, so the tests can bind to local config and become order-dependent.
- Unused imports and an unused local variable remain in modified tests, which violates the test quality criteria even though the current lint script does not scan `tests/`.
- main has a newer commit not merged; diff was computed from merge-base as required.

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_session_lifecycle.py`
- Coverage: session create → tmux create → terminate → output cleanup → db deletion
- Quality: uses real db and cleanup flow with mocked tmux boundary

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Do not test private methods | ✅ | New tests use public entry points (`refresh`, `handle_enter`, `teleclaude__start_session`). |
| Deterministic tests (no external config reliance) | ❌ | `tests/unit/test_preparation_view.py`, `tests/unit/test_mcp_handlers.py` do not set `TELECLAUDE_CONFIG_PATH` before imports. |
| No unused imports or vars | ❌ | Unused imports in `tests/unit/test_sessions_view.py` and `tests/unit/test_mcp_handlers.py`; unused local in `tests/integration/test_feedback_cleanup.py`. |
| Docstrings for every test | ✅ | Added across new and edited files. |
| No loops or conditionals in tests | ⚠️ | Some assertions use list comprehensions and generator expressions (for example `tests/unit/test_adapter_client.py`). |

## Critical Issues (must fix)

- None.

## Important Issues (should fix)

- [tests] `tests/unit/test_preparation_view.py:11` — `PreparationView` imports config at module load, but `TELECLAUDE_CONFIG_PATH` is never set in this test file. This makes the test depend on local config and order of execution.
  - Suggested fix: set `os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")` before importing `PreparationView`.
- [tests] `tests/unit/test_mcp_handlers.py:5` — Same config isolation issue for `MCPHandlersMixin`, plus unused imports (`patch`, `ThinkingMode`).
  - Suggested fix: add `os.environ.setdefault(...)` before the teleclaude import and remove unused imports.
- [tests] `tests/unit/test_sessions_view.py:16` — Unused imports (`CreateSessionResult`, `ProjectWithTodosInfo`, `TreeNode`) should be removed to meet test quality criteria.
  - Suggested fix: remove unused imports.
- [tests] `tests/integration/test_feedback_cleanup.py:54` — `initial_delete_calls` is unused after refactor.
  - Suggested fix: remove the unused local variable.

## Suggestions (nice to have)

- [tests] `tests/unit/test_adapter_client.py:176` — Replace list comprehension and `next(...)` assertions with direct lookups or explicit expected structures to align with the “no loops or conditionals in tests” requirement.

## Strengths

- Priority 0 coverage added for pane manager, sessions view, preparation view, and MCP handler helper behavior.
- Integration fixture now isolates REST socket paths for parallel runs and sets test config in multiple integration suites.
- Docstrings and naming consistency improved across a wide set of test files.

## Verdict

**[ ] APPROVE** — Ready to merge
**[x] REQUEST CHANGES** — Fix critical and important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Set `TELECLAUDE_CONFIG_PATH` before importing config-backed modules in `tests/unit/test_preparation_view.py` and `tests/unit/test_mcp_handlers.py`.
2. Remove unused imports and unused locals in modified tests.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Config isolation in `test_preparation_view.py` | Set `TELECLAUDE_CONFIG_PATH` before import | `a01ca65` |
| Config isolation and unused imports in `test_mcp_handlers.py` | Set `TELECLAUDE_CONFIG_PATH` and removed `patch`, `ThinkingMode` | `f269c69` |
| Unused imports in `test_sessions_view.py` | Removed `CreateSessionResult`, `ProjectWithTodosInfo`, `TreeNode` | `be5e061` |
| Unused local in `test_feedback_cleanup.py` | Removed `initial_delete_calls` | `508bddc` |
| Loops/conditionals in `test_adapter_client.py` | Replaced `next()` and list comprehension with direct indexing | `44ccfd7` |
