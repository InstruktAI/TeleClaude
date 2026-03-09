# Input: tso-tui

Parent: test-suite-overhaul

## Problem

TUI has <10% dedicated unit test coverage (per audit). 98 curses-era tests were deleted (see `tests/ignored.md`). The Textual-based TUI needs fresh behavioral tests across views, widgets, animations, and configuration components.

## Scope

Source files to cover (1:1 mapping):
- `teleclaude/cli/tui/` top-level (21 files)
- `teleclaude/cli/tui/animations/` (5 files)
- `teleclaude/cli/tui/animations/sprites/` (7 files)
- `teleclaude/cli/tui/config_components/` (2 files)
- `teleclaude/cli/tui/utils/` (2 files)
- `teleclaude/cli/tui/views/` (7 files)
- `teleclaude/cli/tui/widgets/` (16 files)

Total: ~60 source files

This is the largest worker scope. Prioritize views and widgets (user-facing behavior) over animations/sprites (visual-only).

## Worker procedure

For each source file:
1. Read the source file's public interface
2. Find existing test coverage in `tests/unit/cli/tui/`
3. Triage: keep behavioral tests, rewrite implementation-coupled ones, delete junk
4. Create/migrate to `tests/unit/cli/tui/<subdir>/test_<name>.py`
5. Each test function gets a behavioral contract docstring

## Constraints

- No source files modified
- No more than 5 `@patch` decorators per test function
- No hard-coded string assertions
- Textual widget tests use Textual's `async with app.run_test()` pattern where appropriate
- Animation/sprite files may be exempt if they contain only data definitions (add to `ignored.md`)
- `__init__.py` files with only imports are exempt

## Success criteria

- Every source file has a 1:1 test file OR is in `tests/ignored.md`
- All new tests pass
- All tests have behavioral docstrings
- Views and widgets have priority coverage
