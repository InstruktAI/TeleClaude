# Code Review: tui-snapshot-tests

**Reviewed**: 2026-01-11
**Reviewer**: Claude Opus 4.5 (Review Agent)

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Phase 1: View Architecture Refactor | ✅ | BaseView + get_render_lines() implemented correctly |
| Task 1.1: Audit existing view classes | ✅ | View structure documented in plan |
| Task 1.2: Add get_render_lines() to BaseView | ✅ | Clean implementation in base.py:8-24 |
| Task 1.3: Refactor SessionsView | ✅ | _format_item() and _format_session() extracted properly |
| Task 1.4: Refactor PreparationView | ✅ | _format_item(), _format_todo(), _format_file() extracted |
| Phase 2: Test Infrastructure | ⚠️ | Partially complete - factories done, harness missing |
| Task 2.1: Mock data factories | ✅ | create_mock_session/computer/project in conftest.py |
| Task 2.2: MockAPIClient | ✅ | Event simulation working |
| Task 2.3: TUIAppTestHarness | ❌ | Not implemented |
| Phase 3: View Logic Tests | ✅ | 23 tests covering SessionsView and PreparationView |
| Phase 4: Data Flow Tests | ❌ | Not implemented - unchecked in plan |
| Phase 5: Reconnection & Edge Cases | ❌ | Not implemented - unchecked in plan |
| Phase 6: CI Integration | ❌ | Not implemented - unchecked in plan |

## Critical Issues (must fix)

1. **[lint]** `tests/conftest.py` - Missing `# guard: loose-dict` comments on dict typings
   - Lines 44, 83, 104, 125-128, 130, 138, 148, 163: `dict[str, object]` typings missing guard comments
   - Pre-commit hook fails: `guardrails: loose dict typings detected (11 > 0)`
   - **Suggested fix**: Add `# guard: loose-dict` comment to each line with `dict[str, object]` OR convert to TypedDict

## Important Issues (should fix)

1. **[incomplete]** `todos/tui-snapshot-tests/implementation-plan.md` - Phases 4-6 remain uncompleted
   - Task 2.3: TUIAppTestHarness not implemented
   - Phase 4: Data Flow Integration Tests not implemented
   - Phase 5: Reconnection & Edge Cases not implemented
   - Phase 6: CI Integration (Makefile targets, docs) not implemented
   - **Suggested fix**: Either implement remaining phases or update implementation plan to reflect actual scope delivered (Phase 1-3 only) and create follow-up work items for deferred phases

## Suggestions (nice to have)

1. **[tests]** `tests/unit/test_tui_sessions_view.py:14-20` - MockFocus class duplicated across both test files
   - Could be moved to conftest.py for reuse
   - Minor duplication, not blocking

2. **[types]** `tests/conftest.py:44` - Return type uses `dict[str, object]`
   - Consider using TypedDict for more precise typing of session/computer/project data
   - Would improve IDE autocomplete and type checking

3. **[docs]** No documentation for TUI testing added as specified in Phase 6 Task 6.3
   - Would help future contributors understand the test harness

## Strengths

- **Clean separation of concerns**: `get_render_lines()` completely decouples render logic from curses
- **Comprehensive view testing**: 23 tests cover empty states, data rendering, scrolling, truncation, indentation
- **Fast tests**: All 23 tests run in <1s with parallel execution
- **Follows project patterns**: Proper use of TreeNode/PrepTreeNode, consistent formatting
- **Well-structured factories**: Mock data factories are reusable and well-typed
- **No curses dependency in tests**: Tests can run in CI without display

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. **BLOCKING**: Fix lint errors in `tests/conftest.py` - add `# guard: loose-dict` comments or convert to TypedDict
2. Decide on scope: Either complete Phases 4-6 OR update implementation plan to reflect that only Phase 1-3 were delivered, then create follow-up work items for the remaining phases

**Rationale**:
- The pre-commit hook fails due to missing guard comments on loose dict typings - this blocks merging
- The implementation plan shows Phases 4-6 as uncompleted (`[ ]` checkboxes). Either the plan needs updating to reflect the actual scope, or the remaining work needs to be completed. The work that WAS done (Phases 1-3) is high quality and the tests pass.
