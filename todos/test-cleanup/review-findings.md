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
| Tests verify behavior over internal calls | `tests/unit/test_adapter_client.py:405` | pytest → AdapterClient.send_output_update | `test_send_output_update_missing_thread_recreates_topic` | ❌ |
| Determinism (no real time reliance) | `tests/unit/test_db.py:273` | pytest → Db.update_last_activity | `test_update_last_activity` | ❌ |
| Clarity (docstrings + naming) | `tests/unit/test_preparation_view.py:54` | pytest → PreparationView.handle_enter | `test_handle_enter_on_ready_todo_splits_tmux_in_tmux_env` | ✅ |
| Mocking only at system boundaries | `tests/unit/test_adapter_client.py:405` | pytest → AdapterClient.send_output_update | `test_send_output_update_missing_thread_recreates_topic` | ❌ |
| Priority 0 coverage added | `tests/unit/test_pane_manager.py:22` | pytest → TmuxPaneManager.show_session | `test_show_session_tracks_parent_and_child_panes` | ✅ |

**Verification notes:**
- Specialized review skills (`next-code-reviewer`, `next-test-analyzer`, `next-silent-failure-hunter`, `next-type-design-analyzer`, `next-comment-analyzer`, `next-code-simplifier`) are not available in this environment; review performed manually.

### Integration Test Check
- Main flow integration test exists: yes
- Test file: `tests/integration/test_session_lifecycle.py`
- Coverage: create session → terminate → output cleanup → DB deletion
- Quality: uses real DB; tmux boundary mocked

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Production code is sacrosanct | ✅ | Diff touches tests and todo metadata only. |
| Tests verify behavior, not internal calls | ❌ | Internal call assertions remain in `tests/unit/test_adapter_client.py:405` and `tests/unit/test_adapter_client.py:547`. |
| Deterministic tests (no real time or sleeps) | ❌ | `tests/unit/test_db.py:279` uses `asyncio.sleep`; `tests/unit/test_daemon.py:861` uses `datetime.now`. |
| No import-outside-toplevel | ❌ | Inline imports remain in `tests/unit/test_db.py:257` and `tests/unit/test_daemon.py:851`. |
| Docstrings for every test | ✅ | Docstrings present in new and edited tests. |

## Critical Issues (must fix)

- None.

## Important Issues (should fix)

- [tests] `tests/unit/test_db.py:257` — Inline imports remain inside tests, violating the import-outside-toplevel directive.
  - Suggested fix: move `SessionAdapterMetadata` and `TelegramAdapterMetadata` imports (and `asyncio` for `test_update_last_activity`) to module top-level.
- [tests] `tests/unit/test_db.py:279` — Test relies on real time via `asyncio.sleep`, violating determinism requirements.
  - Suggested fix: patch time or inject a fixed timestamp so `update_last_activity` can be asserted without sleeping.
- [tests] `tests/unit/test_adapter_client.py:405` — Tests still assert internal call behavior (`ensure_ui_channels.assert_called`), which conflicts with the behavior-over-implementation requirement.
  - Suggested fix: assert on observable outcomes only (message id returned, metadata cleared, or persisted DB state) and remove internal call assertions.

## Suggestions (nice to have)

- [tests] `tests/unit/test_daemon.py:861` — Replace `datetime.now()` usage with a fixed time to keep cleanup tests deterministic.

## Strengths

- Priority 0 coverage added for pane manager, sessions view, preparation view, MCP helper, and DB initiator storage.
- Integration fixtures now isolate REST socket paths for parallel execution.
- Docstrings and naming consistency improved across new and edited tests.

## Verdict

**[ ] APPROVE** — Ready to merge
**[x] REQUEST CHANGES** — Fix critical and important issues first

### If REQUEST CHANGES:

Priority fixes:
1. Remove inline imports in changed tests (`tests/unit/test_db.py`, `tests/unit/test_daemon.py`).
2. Remove real-time sleeps and `datetime.now` usage from tests to restore determinism.
3. Replace internal call assertions in `tests/unit/test_adapter_client.py` with outcome-based checks.
