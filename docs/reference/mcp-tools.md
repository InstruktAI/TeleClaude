---
id: reference/mcp-tools
type: reference
scope: global
description: Complete catalog of available MCP tools for AI agents.
---

## What it is

- Catalog of MCP tools exposed by TeleClaude for discovery, orchestration, and lifecycle management.
- Use this list to select the smallest tool that satisfies the intent.

## Canonical fields

- **Discovery**: `teleclaude__list_computers`, `teleclaude__list_projects`, `teleclaude__list_sessions`.
- **Lifecycle**: `teleclaude__start_session`, `teleclaude__run_agent_command`, `teleclaude__send_message`, `teleclaude__get_session_data`, `teleclaude__stop_notifications`, `teleclaude__end_session`.
- **Files & Results**: `teleclaude__send_file`, `teleclaude__send_result`.
- **Orchestration**: `teleclaude__next_prepare`, `teleclaude__next_work`, `teleclaude__mark_phase`, `teleclaude__set_dependencies`.
- **Maintenance**: `teleclaude__deploy`, `teleclaude__mark_agent_unavailable`.

## Allowed values

- Tool names must match the registered MCP tool list exactly.
- Prefer dedicated tools over ad‑hoc shell commands when available.

## Known caveats

- `teleclaude__run_agent_command` and `teleclaude__send_message` require a 5‑minute wait/timeout workflow for completion checks.
- Long‑running orchestration should use the next‑machine tools to preserve state.
