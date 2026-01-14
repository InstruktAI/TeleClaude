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
| Production code is sacrosanct (tests-only changes) | N/A — tests-only diff | N/A | N/A | ✅ |
| Tests are black box (public entry points) | `tests/unit/test_sessions_view.py:39` | pytest → SessionsView.refresh/handle_enter | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Behavior over implementation (outcomes vs internal calls) | `tests/unit/test_adapter_client.py:397` | pytest → AdapterClient.discover_peers | `test_adapter_client_discover_peers_redis_disabled` | ⚠️ |
| Independence (no shared mutable state) | `tests/unit/test_pane_manager.py:13` | pytest → TmuxPaneManager.toggle_session | `test_toggle_session_returns_false_when_not_in_tmux` | ❌ |
| Determinism (config isolated) | `tests/unit/test_preparation_view.py:11` | import → config load | `test_handle_enter_on_ready_todo_splits_tmux_in_tmux_env` | ✅ |
| Clarity (docstrings + naming) | `tests/unit/test_mcp_handlers.py:40` | pytest → teleclaude__start_session | `test_start_session_extracts_tmux_name_from_event_result` | ✅ |
| Mocking at system boundaries only | `tests/unit/test_pane_manager.py:29` | pytest → TmuxPaneManager.show_session | `test_show_session_tracks_parent_and_child_panes` | ⚠️ |
| Async tests use pytest.mark.asyncio + AsyncMock | `tests/unit/test_sessions_view.py:39` | pytest → SessionsView.refresh | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Priority 0 coverage added (pane manager, sessions view, preparation view, MCP helper, DB initiator) | `tests/unit/test_pane_manager.py:23` | pytest → TmuxPaneManager.show_session/toggle_session/hide_sessions | `test_show_session_tracks_parent_and_child_panes` | ✅ |

**Verification notes:**
- Specialized review skills (`next-code-reviewer`, `next-test-analyzer`, etc.) are not available in this environment; review performed manually.
- The test quality requirements forbid loops/conditionals and import-outside-toplevel; several new or edited tests still violate these rules (see findings).

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_session_lifecycle.py`
- Coverage: session create → tmux create → terminate → output cleanup → db deletion
- Quality: uses real DB with tmux boundary mocked

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Tests clean up after themselves | ❌ | `tests/unit/test_pane_manager.py` mutates `TMUX` env without restore. |
| No import-outside-toplevel | ❌ | Inline import in `tests/integration/test_feedback_cleanup.py`; multiple in `tests/unit/test_adapter_client.py`. |
| No loops/conditionals in tests | ❌ | List comprehensions / `any(...)` in `tests/unit/test_pane_manager.py` and `tests/unit/test_adapter_client.py`. |
| Tests verify behavior, not internal calls | ⚠️ | Some assertions still rely on call counts rather than outcomes. |
| Docstrings for every test | ✅ | Docstrings present in new and edited tests. |

## Critical Issues (must fix)

- None.

## Important Issues (should fix)

- [tests] `tests/unit/test_pane_manager.py:13` — `os.environ.pop("TMUX", None)` mutates global environment without restoring it, which breaks test independence.
  - Suggested fix: wrap with `patch.dict(os.environ, {"TMUX": ""}, clear=False)` or save and restore the prior value in a `try/finally`.
- [tests] `tests/integration/test_feedback_cleanup.py:71` — `from unittest.mock import call` is imported inside the test body, violating the testing directive that imports must be at module top-level.
  - Suggested fix: move `call` import to the module top level.
- [tests] `tests/unit/test_pane_manager.py:37` — `any(...)` and list comprehensions are used in assertions, violating the “no loops or conditionals in tests” requirement.
  - Suggested fix: compare `mock_run.call_args_list` directly to a static `call(...)` list or index specific calls.
- [tests] `tests/unit/test_adapter_client.py:435` — list comprehensions in assertions violate the same “no loops/conditionals” rule.
  - Suggested fix: assert on `call_args_list` contents via direct indexing or `call(...)` list equality.

## Suggestions (nice to have)

- [tests] `tests/unit/test_adapter_client.py:402` — avoid call-count assertions for internal behavior; assert only on returned peers for behavior-level coverage.

## Strengths

- Priority 0 coverage added for pane manager, sessions view, preparation view, MCP handler helper behavior, and initiator session storage.
- Integration fixtures now isolate REST socket paths for parallel runs and set test config for multiple integration suites.
- Docstrings and naming consistency improved across the edited test files.

## Verdict

**[ ] APPROVE** — Ready to merge
**[x] REQUEST CHANGES** — Fix critical and important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Restore global environment after modifying `TMUX` in `tests/unit/test_pane_manager.py`.
2. Move all inline imports to module top-level and remove list comprehension assertions in test files.
