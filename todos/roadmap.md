# Roadmap

> **Last Updated**: 2025-12-23
> **Status Legend**: `[ ]` = Todo | `[>]` = In Progress | `[x]` = Done

---

## MCP Tools

### [>] Send Result Tool

Add `teleclaude__send_result` MCP tool to allow AI agents to send formatted results (markdown tables, reports, analysis) as separate messages to the user, instead of only showing output in the streaming terminal message.

**Key decisions:**
- Use MarkdownV2 formatting (modern, better escaping)
- Strip outer backticks from AI content, re-wrap with proper formatting
- Messages persist (not auto-deleted like feedback)
- Session ID auto-injected from `TELECLAUDE_SESSION_ID`

---

## [x] AI Model Usage

We hit model API rate limits frequently, causing delays and failures. To mitigate this, we plan to implement dynamic model selection based on availability and cost.

For now we will follow the following paradigm:

1. human talks to Claude Opus
2. the AI acts as master to AI sessions it spawns, so those can just get the Sonnet model.

This way we already have some spread over models, helping against rate limiting.

So settle for CLaude Code sessions to be started with the `--model` flag, but ONLY when initiated from an AI via `teleclaude__start_session`.

So we need to append the `--model=sonnet` part at the right place in the command line args.

Another thing we have to get right is in restart_claude.py to detect wether its an AI session so its appends it there as well. Maybe we have to keep a special field in the session DB for that: `initiated_by_ai: bool`. Yes, that is imperative.

### [x] add --model flag to AI calls

Implemented via `claude_model` field in sessions table. MCP tool `teleclaude__start_session` accepts optional `model` parameter.

---

## Documentation

### [x] AI-to-AI Protocol Documentation

Create `docs/ai-to-ai-protocol.md` with full specification, message format, example flows.

---

## Typing Cleanup

### [ ] Reduce loose dict typings (dict[str, object]/dict[str, Any])

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
