# Input: rlf-services

<!-- Seeded from parent refactor-large-files approved requirements. -->

## Problem

Two service-layer entrypoint files need structural decomposition.

## Targets

| File | Lines | Structure |
|------|-------|-----------|
| `teleclaude/api_server.py` | 3,268 | 2 classes (`_WsClientState`, `APIServer` monolith ~3,000 lines of methods) |
| `teleclaude/daemon.py` | 2,669 | 5 classes including `TeleClaudeDaemon` monolith |

Total: ~5,937 lines.

## Context

- **`api_server.py` is already partially split.** Routes are extracted via `include_router` to `teleclaude/api/` submodules (`streaming.py`, `data_routes.py`, `operations_routes.py`, `todo_routes.py`, `session_access.py`, `auth.py`). But `_setup_routes()` still defines inline routes for sessions (~1,100 lines), computers, agents, settings, chiptunes, notifications, jobs, and WebSocket. These remaining route groups need extraction to additional `api/` router modules.
- Import fanout: `api_server.py` has only 2 importers. `daemon.py` has zero importers (pure entrypoint).
- `daemon.py` natural fault lines: hook outbox logic, session bootstrapping, lifecycle wiring, background services.

## Shared constraints (from parent)

- No behavior changes. Only structural decomposition.
- Target: no module over ~500 lines (soft), hard ceiling 800 lines.
- Use `__init__.py` re-exports for backward-compatible import paths.
- No circular dependencies introduced.
- No test changes (test suite rebuild is a separate todo).
- `make lint` and type checking must pass after decomposition.
- Commit atomically per file or tightly-coupled group.
- Runtime smoke: daemon starts, TUI renders, CLI responds.
