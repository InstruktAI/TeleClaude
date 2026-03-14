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

- Existing tests must keep passing. `make test` must pass after every commit. Do not add new tests — the full test suite rebuild is sequenced after this refactoring (see test-suite-overhaul todo). But existing tests must not break.
- The goal is not just splitting files — it is making the code DRY. Before and during decomposition, identify and extract shared utilities, duplicated patterns, and redundant bootstrapping into shared modules. Splitting without deduplication is a failure.
- Public API and observable runtime behavior must not change. Internal restructuring — extracting shared utilities, consolidating duplicated logic, renaming private helpers — is explicitly required and expected.
- Target: no file over ~800 lines after refactoring. Hard ceiling: 1000 lines.
- Each file can be refactored independently, making this highly parallelizable.
- `make lint` must pass. Do not touch lint or type-checker configuration. Do not add `# noqa` suppressions. Do not add useless comments. The code itself must be clean.
- Runtime smoke test (daemon starts, TUI renders, CLI responds) must pass.

## Constraints

- No behavior changes to public API or observable runtime behavior. Internal consolidation and deduplication is the point.
- All imports across the codebase must be updated to reflect new module locations.
- Public API (what other modules import) must not break.
- Use `__init__.py` re-exports where needed for backward compatibility during the transition.
- Commit atomically per file (or per logical group if files are tightly coupled).
