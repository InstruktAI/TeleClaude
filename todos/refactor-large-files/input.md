# Input: refactor-large-files

<!-- Brain dump — raw thoughts, ideas, context. Prepare when ready. -->

## Problem

Files over 1,000 lines are unmanageable. We have 20 files exceeding this threshold, with the top 4 over 2,900 lines. The largest is 4,329 lines. This directly impedes agent work (context limits, merge conflicts, review difficulty) and human comprehension.

## Targets (verified line counts)

| File | Lines |
|------|-------|
| `cli/telec.py` | 4,329 |
| `core/next_machine/core.py` | 4,168 |
| `api_server.py` | 3,267 |
| `adapters/discord_adapter.py` | 2,949 |
| `daemon.py` | 2,668 |
| `core/db.py` | 2,506 |
| `utils/transcript.py` | 2,328 |
| `core/command_handlers.py` | 2,022 |
| `transport/redis_transport.py` | 1,892 |
| `core/agent_coordinator.py` | 1,619 |
| `cli/tui/app.py` | 1,497 |
| `cli/tool_commands.py` | 1,417 |
| `core/tmux_bridge.py` | 1,403 |
| `helpers/youtube_helper.py` | 1,384 |
| `adapters/telegram_adapter.py` | 1,368 |
| `cli/tui/pane_manager.py` | 1,285 |
| `cli/tui/views/sessions.py` | 1,269 |
| `hooks/checkpoint.py` | 1,214 |
| `core/integration/state_machine.py` | 1,183 |
| `resource_validation.py` | 1,179 |

## Context

- All existing tests have been deleted. The test suite will be rebuilt from scratch AFTER this refactoring completes (see test-suite-overhaul todo which depends on this).
- No tests need to be written as part of this work. Zero. The entire test-suite-overhaul pipeline is sequenced after this.
- The goal is pure structural decomposition: split large files into focused, cohesive modules. No behavior changes. Imports must remain valid throughout.
- Target: no file over ~500 lines after refactoring. Hard ceiling: 800 lines.
- Each file can be refactored independently, making this highly parallelizable.
- After all splitting, a full lint pass (`make lint`) and runtime smoke test (daemon starts, TUI renders, CLI responds) must pass.

## Constraints

- No behavior changes. Only structural decomposition.
- All imports across the codebase must be updated to reflect new module locations.
- Public API (what other modules import) must not break.
- Use `__init__.py` re-exports where needed for backward compatibility during the transition.
- Commit atomically per file (or per logical group if files are tightly coupled).
