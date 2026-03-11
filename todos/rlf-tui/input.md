# Input: rlf-tui

<!-- Seeded from parent refactor-large-files approved requirements. -->

## Problem

Six oversized TUI files need structural decomposition.

## Targets

| File | Lines |
|------|-------|
| `teleclaude/cli/tui/app.py` | 1,496 |
| `teleclaude/cli/tui/pane_manager.py` | 1,286 |
| `teleclaude/cli/tui/views/sessions.py` | 1,269 |
| `teleclaude/cli/tui/views/config.py` | 1,086 |
| `teleclaude/cli/tui/animations/general.py` | 1,074 |
| `teleclaude/cli/tui/views/preparation.py` | 1,020 |

Total: ~7,231 lines across 6 files.

## Context

- All files are within the `cli/tui/` subtree — the Textual-based TUI application.
- Each file is ~1,000-1,500 lines — splits will be modest (2-3 submodules each).
- TUI views typically contain one main widget class with helper methods that can be grouped by concern (rendering, event handling, data loading).
- `app.py` is the main Textual app class.
- `pane_manager.py` handles tmux pane lifecycle and layout.
- The three `views/` files are Textual screens/widgets for sessions, config, and preparation.
- `animations/general.py` contains animation effects for the TUI banner.

## Shared constraints (from parent)

- No behavior changes. Only structural decomposition.
- Target: no module over ~500 lines (soft), hard ceiling 800 lines.
- Use `__init__.py` re-exports for backward-compatible import paths.
- No circular dependencies introduced.
- No test changes (test suite rebuild is a separate todo).
- `make lint` and type checking must pass after decomposition.
- Commit atomically per file or tightly-coupled group.
- Runtime smoke: daemon starts, TUI renders, CLI responds.
