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
| Tests are black box (public entry points) | `tests/unit/test_sessions_view.py:39` | pytest → SessionsView.handle_enter | `test_handle_enter_on_session_toggles_pane` | ✅ |
| Tests verify behavior over implementation | `tests/unit/test_adapter_client.py:392` | pytest → AdapterClient.send_output_update | `test_send_output_update_missing_thread_recreates_topic` | ❌ |
| Independence (no shared mutable state) | `tests/unit/test_pane_manager.py:8` | pytest → TmuxPaneManager.toggle_session | `test_toggle_session_returns_false_when_not_in_tmux` | ✅ |
| Determinism (no time/random reliance) | `tests/unit/test_sessions_view.py:39` | pytest → SessionsView.refresh | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Clarity (docstrings + naming) | `tests/unit/test_mcp_handlers.py:33` | pytest → MCPHandlersMixin.teleclaude__start_session | `test_start_session_extracts_tmux_name_from_event_result` | ✅ |
| Mocking only at system boundaries | `tests/unit/test_adapter_client.py:392` | pytest → AdapterClient.send_output_update | `test_send_output_update_missing_thread_recreates_topic` | ❌ |
| Single-responsibility tests | `tests/unit/test_preparation_view.py:50` | pytest → PreparationView.handle_enter | `test_handle_enter_on_ready_todo_splits_tmux_in_tmux_env` | ✅ |
| Priority 0 coverage added | `tests/unit/test_pane_manager.py:1` | pytest → TmuxPaneManager.show_session/toggle_session | `test_show_session_tracks_parent_and_child_panes` | ✅ |

**Verification notes:**
- Specialized review skills (`next-code-reviewer`, `next-test-analyzer`, etc.) are not available in this environment; review performed manually.

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_session_lifecycle.py`
- Coverage: create session → terminate → output cleanup → db deletion
- Quality: uses real DB; tmux boundary mocked

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| No import-outside-toplevel | ❌ | Inline imports remain in changed tests (e.g., `tests/unit/test_preparation_view.py:25`, `tests/unit/test_command_handlers.py:388`). |
| No loops or conditionals in tests | ❌ | Loops in changed tests (e.g., `tests/unit/test_command_handlers.py:394`). |
| Tests verify behavior, not internal calls | ❌ | Call-count assertions on internal methods in `tests/unit/test_adapter_client.py:399-403`. |
| Docstrings for every test | ✅ | Docstrings present in new and edited tests. |

## Critical Issues (must fix)

- None.

## Important Issues (should fix)

- [tests] `tests/unit/test_preparation_view.py:25` — Inline import inside `DummyAPI.create_session` violates the no import-outside-toplevel directive.
  - Suggested fix: move `CreateSessionResult` import to module top-level and use it in the stub.
- [tests] `tests/unit/test_command_handlers.py:394` — `for` loops in test setup and assertions violate the “no loops/conditionals in tests” requirement.
  - Suggested fix: build explicit session fixtures without loops and assert on explicit entries by index.
- [tests] `tests/unit/test_adapter_client.py:399` — Tests assert `ensure_ui_channels` and DB call counts, which are internal implementation details rather than observable behavior.
  - Suggested fix: assert on returned session metadata or output values and avoid internal call-count checks.

## Suggestions (nice to have)

- [tests] `tests/unit/test_adapter_client.py:399` — Where system-boundary validation is needed, prefer checking exact adapter call arguments once instead of call counts plus index assertions.

## Strengths

- Priority 0 coverage added for pane manager, sessions view, preparation view, MCP handler helper, and DB initiator storage.
- Integration fixtures isolate REST socket paths for parallel execution and set test config for integration suites.
- Docstrings and naming consistency improved across new and edited tests.

## Verdict

**[ ] APPROVE** — Ready to merge
**[x] REQUEST CHANGES** — Fix critical and important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Remove inline imports from changed tests (start with `tests/unit/test_preparation_view.py`).
2. Eliminate loops/conditionals in changed tests per requirements (e.g., `tests/unit/test_command_handlers.py`).
3. Replace internal call-count assertions with outcome-based checks in `tests/unit/test_adapter_client.py`.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Inline imports | Moved imports to top-level in `test_preparation_view.py`, `test_command_handlers.py`, `test_daemon.py`, and `test_voice_message_handler.py`. | aec1462 |
| Loops in tests | Removed loops from `test_handle_list_sessions_formats_output` and replaced generator expression in `test_handle_ctrl_requires_key_argument`. | e88a757 |
| Call-count assertions | Replaced `call_count` checks with outcome-based assertions (metadata validation and retry success) in `test_adapter_client.py`. | dc55a87 |
