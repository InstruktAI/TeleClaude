# Input: rlf-cli

<!-- Seeded from parent refactor-large-files approved requirements. -->

## Problem

Two oversized files in the CLI entrypoint layer need structural decomposition.

## Targets

| File | Lines | Structure |
|------|-------|-----------|
| `teleclaude/cli/telec.py` | 4,329 | 5 data classes + `CLI_SURFACE` dict (lines 177-960) + 89 handler functions grouped by command |
| `teleclaude/cli/tool_commands.py` | 1,417 | Tool command handlers invoked by telec.py dispatch |

## Context

- `telec.py` has no split started. The 89 `_handle_*` functions are already partitioned by command group (sessions, todo, roadmap, bugs, docs, config, content, events, signals, auth, history, memories).
- The `CLI_SURFACE` dict and command dispatch logic are shared infrastructure that stays in the main module.
- `tool_commands.py` contains handlers for tool-specific CLI operations.
- Import fanout is low (4 files import from `telec.py`).
- No `teleclaude/cli/telec/` subdirectory exists yet.

## Shared constraints (from parent)

- No behavior changes. Only structural decomposition.
- Target: no module over ~500 lines (soft), hard ceiling 800 lines.
- Use `__init__.py` re-exports for backward-compatible import paths.
- No circular dependencies introduced.
- No test changes (test suite rebuild is a separate todo).
- `make lint` and type checking must pass after decomposition.
- Commit atomically per file or tightly-coupled group.
- Runtime smoke: daemon starts, TUI renders, CLI responds.
