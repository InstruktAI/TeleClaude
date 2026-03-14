# Requirements: chartest-tui-views

Characterization tests for TUI views and widgets.

## Goal

Write characterization tests that pin current behavior of all listed source files
at their public boundaries, creating a safety net for future refactoring.

## Scope

### In scope

- Characterization tests for every listed source file
- 1:1 source-to-test file mapping under `tests/unit/`

### Out of scope

- Modifying production code
- Adding new features
- Refactoring existing code

## Source files

- `teleclaude/cli/tui/views/_config_constants.py`
- `teleclaude/cli/tui/views/base.py`
- `teleclaude/cli/tui/views/config.py`
- `teleclaude/cli/tui/views/config_editing.py`
- `teleclaude/cli/tui/views/config_render.py`
- `teleclaude/cli/tui/views/interaction.py`
- `teleclaude/cli/tui/views/jobs.py`
- `teleclaude/cli/tui/views/preparation.py`
- `teleclaude/cli/tui/views/preparation_actions.py`
- `teleclaude/cli/tui/views/sessions.py`
- `teleclaude/cli/tui/views/sessions_actions.py`
- `teleclaude/cli/tui/views/sessions_highlights.py`
- `teleclaude/cli/tui/widgets/activity_row.py`
- `teleclaude/cli/tui/widgets/agent_badge.py`
- `teleclaude/cli/tui/widgets/agent_status.py`
- `teleclaude/cli/tui/widgets/banner.py`
- `teleclaude/cli/tui/widgets/box_tab_bar.py`
- `teleclaude/cli/tui/widgets/computer_header.py`
- `teleclaude/cli/tui/widgets/group_separator.py`
- `teleclaude/cli/tui/widgets/job_row.py`
- `teleclaude/cli/tui/widgets/modals.py`
- `teleclaude/cli/tui/widgets/project_header.py`
- `teleclaude/cli/tui/widgets/status_bar.py`
- `teleclaude/cli/tui/widgets/telec_footer.py`
- `teleclaude/cli/tui/widgets/todo_file_row.py`
- `teleclaude/cli/tui/widgets/todo_row.py`

## Success criteria

- [ ] Every listed source file has a corresponding test file (or documented exemption)
- [ ] Tests pin actual behavior at public boundaries
- [ ] All tests pass on current codebase
- [ ] No string assertions on human-facing text
- [ ] Max 5 mock patches per test
- [ ] Each test name reads as a behavioral specification
- [ ] All existing tests still pass (no regressions)
- [ ] Lint and type checks pass

## Constraints

- Recommended agent: **codex**
- Follow OBSERVE-ASSERT-VERIFY cycle (not RED-GREEN-REFACTOR)
- Tests pass immediately — this is expected for characterization

## Methodology: Characterization Testing (OBSERVE-ASSERT-VERIFY)

Follow the OBSERVE-ASSERT-VERIFY cycle per source file. See testing policy for full details.

### Rules

- Test at public API boundaries only
- Behavioral contracts, not implementation details
- No string assertions on human-facing text
- Max 5 mock patches per test
- One clear expectation per test
- Mock at architectural boundaries (I/O, DB, network)
- Every test must answer: "What real bug in OUR code would this catch?"
- 1:1 source-to-test mapping
- Use pytest with standard fixtures
- Skip files with genuinely no testable logic — document why
