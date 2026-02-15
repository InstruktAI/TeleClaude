---
id: 'project/spec/mcp-tool-surface'
type: 'spec'
scope: 'project'
description: 'Authoritative surface for Model Context Protocol (MCP) tools.'
---

# MCP Surface — Spec

## Definition

Model Context Protocol (MCP) tools enable AI agents to interact with the TeleClaude daemon and remote computers. This specification defines the stable tool names and their expected function.

## Machine-Readable Surface

```yaml
namespace: teleclaude
tools:
  teleclaude__help:
    description: 'Return a short description of TeleClaude capabilities.'
  teleclaude__get_context:
    description: 'Retrieve relevant documentation snippets.'
  teleclaude__list_computers:
    description: 'List all available TeleClaude computers in the network.'
  teleclaude__list_projects:
    description: 'List available project directories on a target computer.'
  teleclaude__list_sessions:
    description: 'List active sessions from local or remote computer(s).'
  teleclaude__start_session:
    description: 'Start a new session (Claude, Gemini, or Codex) on a remote computer.'
  teleclaude__send_message:
    description: 'Send a message to an existing AI Agent session.'
  teleclaude__run_agent_command:
    description: 'Start a new AI agent session and give it a slash command to execute.'
  teleclaude__get_session_data:
    description: 'Retrieve session data (transcript) from a local or remote session.'
  teleclaude__deploy:
    description: 'Deploy latest code to remote computers (git pull + restart).'
  teleclaude__send_file:
    description: 'Send a file to the specified TeleClaude session for download.'
  teleclaude__send_result:
    description: 'Send formatted results to the user as a separate message.'
  teleclaude__stop_notifications:
    description: "Unsubscribe from a session's stop/notification events."
  teleclaude__end_session:
    description: 'Gracefully end a Claude Code session (local or remote).'
  teleclaude__next_prepare:
    description: 'Phase A state machine: Check preparation state and return instructions.'
  teleclaude__next_work:
    description: 'Phase B state machine: Check build state and return instructions.'
  teleclaude__next_maintain:
    description: 'Phase D state machine: Maintenance stub.'
  teleclaude__mark_phase:
    description: 'Mark a work phase as complete/approved in state.json.'
  teleclaude__set_dependencies:
    description: 'Set dependencies for a work item.'
  teleclaude__mark_agent_status:
    description: 'Set agent dispatch status (available/unavailable/degraded).'
  teleclaude__mark_agent_unavailable:
    description: 'Mark an agent as temporarily unavailable (legacy alias for mark_agent_status).'
  teleclaude__publish:
    description: 'Publish a message to an internal Redis Stream channel.'
  teleclaude__channels_list:
    description: 'List configured internal channels and their subscriptions.'
```

## Constraints

- Tool name renames or removals are breaking changes (Minor bump).
- Changes to input schema required fields are breaking changes.
- Changes to descriptions or adding optional fields are patches.
