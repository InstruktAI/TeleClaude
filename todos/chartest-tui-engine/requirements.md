# Requirements: chartest-tui-engine

Characterization tests for TUI core engine.

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

- `teleclaude/cli/tui/_pane_specs.py`
- `teleclaude/cli/tui/app_actions.py`
- `teleclaude/cli/tui/app_media.py`
- `teleclaude/cli/tui/app_ws.py`
- `teleclaude/cli/tui/base.py`
- `teleclaude/cli/tui/color_utils.py`
- `teleclaude/cli/tui/config_components/guidance.py`
- `teleclaude/cli/tui/controller.py`
- `teleclaude/cli/tui/messages.py`
- `teleclaude/cli/tui/pane_bridge.py`
- `teleclaude/cli/tui/pane_layout.py`
- `teleclaude/cli/tui/pane_manager.py`
- `teleclaude/cli/tui/pane_theming.py`
- `teleclaude/cli/tui/persistence.py`
- `teleclaude/cli/tui/pixel_mapping.py`
- `teleclaude/cli/tui/prep_tree.py`
- `teleclaude/cli/tui/session_launcher.py`
- `teleclaude/cli/tui/state.py`
- `teleclaude/cli/tui/state_store.py`
- `teleclaude/cli/tui/theme.py`
- `teleclaude/cli/tui/todos.py`
- `teleclaude/cli/tui/tree.py`
- `teleclaude/cli/tui/utils/formatters.py`

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
