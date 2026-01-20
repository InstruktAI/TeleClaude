---
id: reference/mcp-tools
type: reference
scope: global
description: Complete catalog of available MCP tools for AI agents.
---

# MCP Tools Reference

## Discovery
- `teleclaude__list_computers`: List online computers.
- `teleclaude__list_projects`: List trusted project directories.
- `teleclaude__list_sessions`: List active AI-to-AI sessions.

## Lifecycle
- `teleclaude__start_session`: Start a new AI worker session.
- `teleclaude__run_agent_command`: Run a slash command (starts session if needed).
- `teleclaude__send_message`: Send message to an existing session.
- `teleclaude__get_session_data`: Retrieve transcript/state (tail/time-filtered).
- `teleclaude__stop_notifications`: Unsubscribe from session events.
- `teleclaude__end_session`: Terminate session and cleanup resources.

## Files & Results
- `teleclaude__send_file`: Send a file to a session's Telegram chat.
- `teleclaude__send_result`: Send formatted Markdown/HTML results to user.

## Orchestration
- `teleclaude__next_prepare`: Prepare a work item (HITL).
- `teleclaude__next_work`: Start autonomous work on a prepared item.
- `teleclaude__mark_phase`: Mark build/review phase status.
- `teleclaude__set_dependencies`: Define task dependencies.

## Maintenance
- `teleclaude__deploy`: Trigger `git pull` + `make install` on remotes.
- `teleclaude__mark_agent_unavailable`: Handle rate limits or outages.