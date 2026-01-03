# Roadmap

> **Last Updated**: 2026-01-03
> **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
> (DONE work is tracked in [delivered.md](./delivered.md))

---

## Typing Cleanup

- [ ] reduce-loose-dict-typings
Reduce loose dict typings (`dict[str, object]` / `dict[str, Any]`) across the codebase.

Inventory (excluding `teleclaude/adapters/redis_adapter.py`):

- `teleclaude/mcp_server.py` (23)
- `teleclaude/utils/claude_transcript.py` (23)
- `teleclaude/core/adapter_client.py` (14)
- `teleclaude/core/models.py` (12)
- `teleclaude/daemon.py` (8)
- `teleclaude/core/events.py` (7)
- `teleclaude/core/ux_state.py` (6)
- `teleclaude/core/command_handlers.py` (5)
- `teleclaude/core/computer_registry.py` (4)
- `teleclaude/hooks/adapters/claude.py` (4)
- `teleclaude/hooks/adapters/gemini.py` (4)
- `teleclaude/hooks/receiver.py` (4)
- `teleclaude/config.py` (3)
- `teleclaude/core/agent_parsers.py` (3)
- `teleclaude/adapters/telegram_adapter.py` (2)
- `teleclaude/core/metadata.py` (2)
- `scripts/guardrails.py` (1)
- `teleclaude/adapters/ui_adapter.py` (1)
- `teleclaude/core/agent_coordinator.py` (1)
- `teleclaude/core/parsers.py` (1)
- `teleclaude/core/system_stats.py` (1)
- `teleclaude/hooks/utils/parse_helpers.py` (1)
- `teleclaude/utils/__init__.py` (1)
