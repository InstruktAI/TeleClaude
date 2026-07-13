---
description: Claude Code Hooks
---

# Claude Code Hooks

## Overview

Claude Code hooks run shell commands at lifecycle events. Hooks are configured in settings
files and receive JSON input describing the event.

## Configuration locations

- `~/.claude/settings.json`
- `.claude/settings.json`
- `.claude/settings.local.json`

Managed settings can be enforced by policy files.

## Hook events

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse`
- `PostToolUseFailure`
- `SubagentStart`
- `SubagentStop`
- `Stop`
- `PreCompact`
- `SessionEnd`
- `Notification`
- `Elicitation`
- `ElicitationResult`

## Hook input contract (selected fields we use)

Base fields (all events):

- `session_id` (string)
- `transcript_path` (string)
- `permission_mode` (string: `default`, `plan`, `acceptEdits`, `bypassPermissions`)
- `hook_event_name` (string)

SessionStart fields:

- `source` (`startup`)

UserPromptSubmit fields:

- `prompt` (string)

Stop fields:

- `stop_hook_active` (boolean)
- `last_assistant_message` (optional string)

SessionEnd fields:

- `reason` (`exit`)

Notification fields:

- `message` (string)
- `title` (optional string)
- `notification_type`:
  - `permission_prompt`
  - `idle_prompt`
  - `auth_success`
  - `elicitation_dialog`
  - `elicitation_complete`
  - `elicitation_response`
  - `agent_needs_input` (Claude Code 2.1.198+; background session waiting for input)
  - `agent_completed` (Claude Code 2.1.198+; background session finished or failed)

`Notification` is an observability/side-effect hook. It cannot block or modify the
native notification. `PermissionRequest` is the separate pre-prompt decision hook;
`Elicitation` and `ElicitationResult` are the separate MCP interaction hooks.

## TeleClaude adapter mapping

Mapping rules:

- `SessionStart` → `event_type = "session_start"`
  - Requires `data.session_id` (native session id).
  - Requires `data.transcript_path` (native transcript path).
- `UserPromptSubmit` → `event_type = "prompt"`
  - Extracts `data.prompt` to update `last_message_sent` in the database.
- `PreToolUse` → `event_type = "tool_use"` (drives TUI activity)
- `Stop` → `event_type = "stop"`
- Other catalogued Claude signatures (`PostToolUse`, `PostToolUseFailure`,
  `SubagentStart`, `SubagentStop`, `SessionEnd`, `PreCompact`) map to `None`.
- `Notification`, `PermissionRequest`, `Elicitation`, and `ElicitationResult` are
  not catalogued or installed by TeleClaude. Native human-attention notifications
  therefore never enter the current TeleClaude notification pipeline.

## Human-attention integration boundary

Claude's native `Notification` event is the authoritative ingress for user-attention
states. TeleClaude should consume the structured notification type and session ID;
it must not infer the same intent from transcript text or tool names. In particular,
`agent_needs_input`, `permission_prompt`, `idle_prompt`, and `elicitation_dialog`
are distinct upstream reasons even when they eventually share a human notification
renderer.

## Sources

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/hooks-guide
