# Input: rlf-adapters

<!-- Seeded from parent refactor-large-files approved requirements. -->

## Problem

Three adapter files need structural decomposition.

## Targets

| File | Lines |
|------|-------|
| `teleclaude/adapters/discord_adapter.py` | 2,951 |
| `teleclaude/adapters/telegram_adapter.py` | 1,368 |
| `teleclaude/adapters/ui_adapter.py` | 1,048 |

Total: ~5,367 lines.

## Context

- **Precedent exists:** `teleclaude/adapters/telegram/` is already a package with mixin-based decomposition — 6 mixin classes across 5 submodules re-exported from `__init__.py`. This is the pattern to follow for adapter splitting.
- `discord_adapter.py` is the largest adapter (2,951 lines). The Discord adapter handles event routing, message rendering, slash commands, and bot lifecycle.
- `ui_adapter.py` translates human inputs into events and renders outputs with UX rules.
- The mixin pattern (splitting a large class into concern-specific mixins) is already proven in this codebase.

## Shared constraints (from parent)

- No behavior changes. Only structural decomposition.
- Target: no module over ~500 lines (soft), hard ceiling 800 lines.
- Use `__init__.py` re-exports for backward-compatible import paths.
- No circular dependencies introduced.
- No test changes (test suite rebuild is a separate todo).
- `make lint` and type checking must pass after decomposition.
- Commit atomically per file or tightly-coupled group.
- Runtime smoke: daemon starts, TUI renders, CLI responds.
