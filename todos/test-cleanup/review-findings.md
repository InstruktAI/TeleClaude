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
| Production code is sacrosanct (tests-only changes) | N/A - tests-only diff | N/A | N/A | ✅ |
| Tests are black box (public entry points) | `tests/unit/test_pane_manager.py:11` | pytest -> TmuxPaneManager.toggle_session | `test_toggle_session_returns_false_when_not_in_tmux` | ✅ |
| Tests verify behavior over internal calls | `tests/unit/test_mcp_server.py:387` (call args assertions) | pytest -> TeleClaudeMCPServer.teleclaude__run_agent_command -> AdapterClient.handle_event | `test_run_agent_command_passes_mode_for_new_session` | ❌ |
| Independence (isolated state per test) | `tests/integration/conftest.py:122` | pytest -> daemon_with_mocked_telegram -> Db.initialize | `test_close_session_full_cleanup` | ✅ |
| Determinism (no real time reliance) | `tests/unit/test_mcp_server.py:76`, `tests/unit/test_computer_registry.py:56`, `tests/unit/test_command_handlers.py:377` | pytest -> helpers with datetime.now | multiple | ❌ |
| Speed (unit tests avoid heavy I/O) | `tests/unit/test_pane_manager.py:22` | pytest -> TmuxPaneManager.show_session | `test_show_session_tracks_parent_and_child_panes` | ✅ |
| Clarity (docstrings and naming) | `tests/unit/test_preparation_view.py:54` | pytest -> PreparationView.handle_enter | `test_handle_enter_on_ready_todo_splits_tmux_in_tmux_env` | ✅ |
| Single responsibility (one behavior per test) | `tests/unit/test_mcp_handlers.py:64` | pytest -> MCPHandlersMixin.teleclaude__start_session | `test_start_session_handles_missing_tmux_name` | ✅ |
| Mocking only at system boundaries | `tests/unit/test_pane_manager.py:22` | pytest -> TmuxPaneManager.show_session -> tmux boundary | `test_show_session_tracks_parent_and_child_panes` | ✅ |
| Arrange-Act-Assert structure | `tests/unit/test_sessions_view.py:39` | pytest -> SessionsView.refresh | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Naming convention (test_<function>_<scenario>_<expected>) | `tests/unit/test_sessions_view.py:39` | pytest -> SessionsView.refresh | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Docstrings for tests | `tests/unit/test_sessions_view.py:40` | pytest -> SessionsView.refresh | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Async testing requirements (pytest.mark.asyncio, AsyncMock) | `tests/unit/test_sessions_view.py:39` | pytest -> SessionsView.refresh | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Error handling tests (exception paths) | `tests/unit/test_hook_receiver.py:14` | pytest -> receiver.main | `test_receiver_emits_error_event_on_normalize_failure` | ✅ |
| Edge cases (missing or malformed data) | `tests/unit/test_mcp_handlers.py:64` | pytest -> MCPHandlersMixin.teleclaude__start_session | `test_start_session_handles_missing_tmux_name` | ✅ |

**Verification notes:**
- Specialized review skills (`next-code-reviewer`, `next-test-analyzer`, `next-silent-failure-hunter`, `next-type-design-analyzer`, `next-comment-analyzer`, `next-code-simplifier`) are not available in this environment, so review was performed manually.

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_session_lifecycle.py`
- Coverage: create session -> terminate -> output cleanup -> DB deletion
- Quality: uses real Db with mocked tmux boundary

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Production code is sacrosanct | ✅ | Diff touches tests and todo metadata only. |
| Tests are black box | ✅ | New TUI and MCP helper tests use public methods. |
| Tests verify behavior, not implementation | ❌ | MCP server tests still assert handle_event call args. |
| Independence | ✅ | Integration fixture isolates DB and REST socket per test. |
| Determinism | ❌ | datetime.now remains in multiple modified tests. |
| Speed | ✅ | Unit tests rely on mocks and avoid heavy I/O. |
| Clarity | ✅ | Docstrings and naming conventions added across edited tests. |
| Single responsibility | ✅ | New tests focus on a single behavior. |
| Mocking at system boundaries only | ✅ | tmux and adapter boundaries are mocked explicitly. |
| Arrange-Act-Assert pattern | ✅ | New tests follow setup, action, assertions. |
| Naming convention | ✅ | New tests follow descriptive naming. |
| Docstrings required | ✅ | New and edited tests include docstrings. |
| Async testing requirements | ✅ | Async tests use pytest.mark.asyncio and AsyncMock. |
| Error handling tests | ✅ | Error paths tested in hook receiver and voice handler. |
| Edge cases | ✅ | Missing tmux session name and idle thresholds covered. |
| Anti-patterns to eliminate (mock-only tests) | ⚠️ | Some call-arg assertions remain in MCP server tests. |

## Critical Issues (must fix)

- None.

## Important Issues (should fix)

- [tests] `tests/unit/test_mcp_server.py:171`, `tests/unit/test_mcp_server.py:281` - Import-outside-toplevel violations remain inside test bodies, which conflicts with testing directives.
  - Suggested fix: move `tempfile` imports to module top and reuse them in tests.
- [tests] `tests/unit/test_mcp_server.py:76`, `tests/unit/test_computer_registry.py:56`, `tests/unit/test_command_handlers.py:377` - Tests still rely on `datetime.now()` which violates determinism requirements.
  - Suggested fix: use fixed timestamps or patch time sources to remove real time dependency.
- [tests] `tests/unit/test_mcp_server.py:387`, `tests/unit/test_mcp_server.py:437` - Tests assert internal call arguments to AdapterClient instead of observable outcomes, which conflicts with behavior-over-implementation guidance.
  - Suggested fix: assert on returned results or record emitted messages via a lightweight fake adapter that surfaces observable behavior.

## Suggestions (nice to have)

- [tests] `tests/integration/conftest.py:140` - REST socket path is assigned twice; consider consolidating to one assignment to reduce fixture noise.

## Strengths

- Priority 0 test coverage added for pane manager, sessions view, preparation view, and MCP helper edge cases.
- Integration fixtures isolate REST socket paths and config to prevent parallel test conflicts.
- Docstrings and naming consistency improved across new and edited tests.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical and important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Remove import-outside-toplevel violations in `tests/unit/test_mcp_server.py`.
2. Replace `datetime.now()` usage in modified tests with fixed timestamps.
3. Refactor MCP server tests to assert outcomes instead of AdapterClient call args.
