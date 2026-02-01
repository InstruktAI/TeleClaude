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

## Hook input contract (selected fields we use)

Base fields (all events):

- `session_id` (string)
- `transcript_path` (string)
- `permission_mode` (string: `default`, `plan`, `acceptEdits`, `bypassPermissions`)
- `hook_event_name` (string)

SessionStart fields:

- `source` (`startup`)

UserPromptSubmit / Stop fields:

- `user_prompt` (string)

SessionEnd fields:

- `reason` (`exit`)

Notification fields:

- `message` (string)
- `notification_type` (`permission_prompt`)

## TeleClaude adapter mapping

Mapping rules:

- `SessionStart` → `event_type = "session_start"`
  - Requires `data.session_id` (native session id).
  - Requires `data.transcript_path` (native transcript path).
- `UserPromptSubmit` → `event_type = "prompt"`
  - Extracts `data.user_prompt` to update `last_message_sent` in the database.
- `Stop` → `event_type = "stop"`
- `Notification` → `event_type = "notification"`
- `SessionEnd` → `event_type = "session_end"` (reserved; no handler logic yet)

## Sources

- https://docs.claude.com/en/docs/claude-code/hooks
- https://code.claude.com/docs/en/hooks-guide#hook-events-overview
