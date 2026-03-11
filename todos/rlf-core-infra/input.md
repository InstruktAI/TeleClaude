# Input: rlf-core-infra

<!-- Seeded from parent refactor-large-files approved requirements. -->

## Problem

Three core infrastructure files need structural decomposition.

## Targets

| File | Lines |
|------|-------|
| `teleclaude/core/agent_coordinator.py` | 1,619 |
| `teleclaude/core/tmux_bridge.py` | 1,402 |
| `teleclaude/core/adapter_client.py` | 1,161 |

Total: ~4,182 lines.

## Context

- `agent_coordinator.py` orchestrates agent session lifecycle, availability, and dispatch.
- `tmux_bridge.py` handles tmux session creation, input injection, and per-session temp directories.
- `adapter_client.py` centralizes UI adapter lifecycle, delivery, and cross-computer routing.
- Each file is ~1,200-1,600 lines — splits will be modest (2-3 submodules each).

## Shared constraints (from parent)

- No behavior changes. Only structural decomposition.
- Target: no module over ~500 lines (soft), hard ceiling 800 lines.
- Use `__init__.py` re-exports for backward-compatible import paths.
- No circular dependencies introduced.
- No test changes (test suite rebuild is a separate todo).
- `make lint` and type checking must pass after decomposition.
- Commit atomically per file or tightly-coupled group.
- Runtime smoke: daemon starts, TUI renders, CLI responds.
