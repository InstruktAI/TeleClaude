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
| Tests are black box (public entry points) | `tests/unit/test_pane_manager.py:11` | pytest → TmuxPaneManager.toggle_session | `test_toggle_session_returns_false_when_not_in_tmux` | ✅ |
| Tests verify behavior over internal calls | `tests/unit/test_mcp_server.py:327` | pytest → TeleClaudeMCPServer.teleclaude__start_session → AdapterClient.handle_event | `test_teleclaude_start_session_with_agent_parameter` | ❌ |
| Independence (isolated state per test) | `tests/unit/test_db.py:16` | pytest → Db fixture → Db.initialize | `test_create_session_minimal` | ✅ |
| Determinism (no real time reliance) | `tests/unit/test_adapter_client.py:128` | pytest → AdapterClient.discover_peers | `test_adapter_client_discover_peers_single_adapter` | ❌ |
| Speed (unit tests avoid heavy I/O) | `tests/unit/test_pane_manager.py:11` | pytest → TmuxPaneManager.toggle_session | `test_toggle_session_returns_false_when_not_in_tmux` | ✅ |
| Clarity (docstrings + readable names) | `tests/unit/test_preparation_view.py:54` | pytest → PreparationView.handle_enter | `test_handle_enter_on_ready_todo_splits_tmux_in_tmux_env` | ✅ |
| Single responsibility (one behavior per test) | `tests/unit/test_mcp_handlers.py:64` | pytest → MCPHandlersMixin.teleclaude__start_session | `test_start_session_handles_missing_tmux_name` | ✅ |
| Mocking only at system boundaries | `tests/unit/test_pane_manager.py:22` | pytest → TmuxPaneManager.show_session → tmux boundary | `test_show_session_tracks_parent_and_child_panes` | ✅ |
| Arrange-Act-Assert structure | `tests/unit/test_db.py:37` | pytest → Db.create_session | `test_create_session_minimal` | ✅ |
| Naming convention (test_<function>_<scenario>_<expected>) | `tests/unit/test_sessions_view.py:39` | pytest → SessionsView.refresh | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Docstrings for every test | `tests/unit/test_sessions_view.py:40` | pytest → SessionsView.refresh | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Async testing requirements (pytest.mark.asyncio, AsyncMock) | `tests/unit/test_sessions_view.py:39` | pytest → SessionsView.refresh | `test_refresh_updates_activity_state_marks_idle_when_activity_is_old` | ✅ |
| Error handling tests (exception paths) | `tests/unit/test_hook_receiver.py:11` | pytest → receiver.main | `test_receiver_emits_error_event_on_normalize_failure` | ✅ |
| Edge cases covered (missing/malformed data) | `tests/unit/test_mcp_handlers.py:64` | pytest → MCPHandlersMixin.teleclaude__start_session | `test_start_session_handles_missing_tmux_name` | ✅ |
| Priority 0 coverage added (new components) | `tests/unit/test_pane_manager.py:22` | pytest → TmuxPaneManager.show_session | `test_show_session_tracks_parent_and_child_panes` | ✅ |

**Verification notes:**
- Specialized review skills (`next-code-reviewer`, `next-test-analyzer`, `next-silent-failure-hunter`, `next-type-design-analyzer`, `next-comment-analyzer`, `next-code-simplifier`) are not available in this environment; review performed manually.

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_session_lifecycle.py`
- Coverage: create session → terminate → output cleanup → DB deletion
- Quality: uses real Db with mocked tmux boundary

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Production code is sacrosanct | ✅ | Diff touches tests and todo metadata only. |
| Tests are black box | ✅ | New TUI and MCP helper tests exercise public methods. |
| Tests verify behavior, not internal calls | ❌ | Internal call assertions remain in MCP server tests. |
| Independence | ✅ | Temporary DB fixture isolates state per test. |
| Determinism | ❌ | Real-time `datetime.now()` used in adapter client and MCP tools tests. |
| Speed | ✅ | Unit tests rely on mocks; no sleeps introduced in new tests. |
| Clarity | ✅ | Docstrings and naming conventions added across edited tests. |
| Single responsibility | ✅ | New tests focus on a single behavior each. |
| Mocking at system boundaries only | ✅ | tmux and adapter boundaries mocked explicitly in new tests. |
| Arrange-Act-Assert pattern | ✅ | New tests follow setup, action, assertions with minimal branching. |
| Naming convention (test_<function>_<scenario>_<expected>) | ✅ | New tests follow descriptive naming. |
| Docstrings required | ✅ | New and edited tests include docstrings. |
| Database testing approach | ✅ | Db tests use real Db (code under test) and avoid alternate engines. |
| Async testing requirements | ✅ | Async tests use pytest.mark.asyncio and AsyncMock. |
| Error handling tests | ✅ | Error paths tested in hook receiver and voice handler tests. |
| Coverage requirements (public functions, error paths, edge cases) | ✅ | Priority 0 components now covered; error and edge paths present. |
| Edge cases (empty/invalid/boundary inputs) | ✅ | Missing tmux session name and idle thresholds covered. |
| Anti-patterns to eliminate (mock-only tests, mega tests) | ⚠️ | Some tests still assert internal call sequences instead of outcomes. |

## Critical Issues (must fix)

- None.

## Important Issues (should fix)

- [tests] `tests/unit/test_computer_registry.py:183`, `tests/unit/test_hook_receiver.py:13`, `tests/unit/test_mcp_server.py:25`, `tests/integration/test_mcp_tools.py:22`, `tests/unit/test_ui_adapter_command_overrides.py:12` — Import-outside-toplevel violations remain in edited tests, which conflicts with testing directives.
  - Suggested fix: move imports to module top level and set env/config before imports when needed.
- [tests] `tests/unit/test_adapter_client.py:128`, `tests/integration/test_mcp_tools.py:39` — Tests still use real time via `datetime.now()` which violates determinism requirements.
  - Suggested fix: replace with fixed timestamps (e.g., `datetime(2024, 1, 1, tzinfo=timezone.utc)`) or patched time sources.
- [tests] `tests/unit/test_mcp_server.py:327` — Tests assert internal call ordering and payloads instead of observable outcomes, which violates the behavior-over-implementation requirement.
  - Suggested fix: assert on returned tool results or persisted state changes rather than `handle_event` call arguments.

## Suggestions (nice to have)

- [tests] `tests/integration/conftest.py:145` — REST socket path is patched twice; consider consolidating to a single path assignment to reduce fixture noise.

## Strengths

- Priority 0 test coverage added for pane manager, sessions view, preparation view, and MCP helper edge cases.
- Integration fixtures isolate REST socket paths and config to prevent parallel test conflicts.
- Docstrings and naming consistency improved across new and edited tests.

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical and important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Remove import-outside-toplevel violations in modified tests.
2. Replace real-time `datetime.now()` usage in tests with fixed timestamps.
3. Replace internal call assertions in MCP server tests with outcome-based checks.
