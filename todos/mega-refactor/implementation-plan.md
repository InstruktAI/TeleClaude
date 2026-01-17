# Implementation Plan — Parallel mega-refactor

## Strategy
- Split work into independent file‑level refactors.
- Each refactor lives in `todos/mega-refactor/plans/` with a tiny per‑file plan.
- Dispatch in parallel because these files do not share code paths beyond imports.

## Files to refactor in parallel
- [>] `teleclaude/daemon.py` (Extractions done, wiring/stability in progress)
- [ ] `teleclaude/adapters/redis_adapter.py`
- [ ] `teleclaude/core/command_handlers.py`
- [ ] `teleclaude/core/next_machine.py`
- [ ] `teleclaude/core/adapter_client.py`
- [ ] `teleclaude/adapters/rest_adapter.py`
- [ ] `teleclaude/core/terminal_bridge.py`
- [ ] `teleclaude/cli/tui/views/preparation.py`
- [ ] `teleclaude/core/db.py`
- [ ] `teleclaude/mcp/handlers.py`
- [ ] `teleclaude/cli/tui/views/sessions.py`

## Per‑file plans
- See `todos/mega-refactor/plans/*.md`