# Roadmap

> **Last Updated**: 2025-12-30
> **Status Legend**: `[ ]` = Todo | `[>]` = In Progress | `[x]` = Done

---

## Development Process

### [>] next-machine - Deterministic workflow state machine

Create `teleclaude__next_step` MCP tool that returns exact commands to execute for the build/review/finalize cycle. Eliminates interpretation from orchestration - the tool tells you exactly what to dispatch next based on file state.

---

## Typing Cleanup

### [ ] Reduce loose dict typings (dict[str, object]/dict[str, Any])

Needs proper inventorization but here's some initial findings:

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
