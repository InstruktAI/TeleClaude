# Input: rlf-core-data

<!-- Seeded from parent refactor-large-files approved requirements. -->

## Problem

Three data-layer files in core need structural decomposition.

## Targets

| File | Lines | Structure |
|------|-------|-----------|
| `teleclaude/core/db.py` | 2,506 | 4 dataclasses + `Db` monolithic class (~2,300 lines of methods) |
| `teleclaude/core/command_handlers.py` | 2,023 | Command handler functions |
| `teleclaude/core/models.py` | 1,095 | Data models and type definitions |

Total: ~5,624 lines.

## Context

- **`db.py` has the highest import fanout in the codebase (45 files).** The `Db` class has clear method groups: session CRUD, hook outbox, inbound queue, operations, webhooks, session listeners, conversation links, voice assignment, agent availability. These map to domain-specific mixin files or sub-files.
- The facade (`__init__.py` re-exports) is mandatory for `db.py` — all 45 importers must continue to work.
- `command_handlers.py` contains handler functions for various command types.
- `models.py` contains Pydantic or dataclass model definitions.

## Shared constraints (from parent)

- No behavior changes. Only structural decomposition.
- Target: no module over ~500 lines (soft), hard ceiling 800 lines.
- Use `__init__.py` re-exports for backward-compatible import paths.
- No circular dependencies introduced.
- No test changes (test suite rebuild is a separate todo).
- `make lint` and type checking must pass after decomposition.
- Commit atomically per file or tightly-coupled group.
- Runtime smoke: daemon starts, TUI renders, CLI responds.
