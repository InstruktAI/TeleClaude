# Claude Code Hooks — Input/Output Shapes

Source: Claude Code official docs (hooks reference).  
Origin: docs.anthropic.com/en/docs/claude-code/hooks  
Last Updated: 2026-01-19

## Configuration (Official)

Hooks are configured in settings files:

- `~/.claude/settings.json` (user)
- `.claude/settings.json` (project)
- `.claude/settings.local.json` (local project)

Structure (per event, with matchers for tool events):

```json
{
  "hooks": {
    "EventName": [
      {
        "matcher": "ToolPattern",
        "hooks": [
          {
            "type": "command",
            "command": "your-command-here"
          }
        ]
      }
    ]
  }
}
```

Notes:
- `matcher` is only applicable for `PreToolUse` and `PostToolUse`.
- Matchers are case‑sensitive tool name patterns.

## Command‑Scoped Hooks (Slash Command Frontmatter)

Claude Code slash command files can define hooks directly in frontmatter.
These hooks are scoped to the command’s execution and cleaned up after the command finishes.
Supported hook keys in command frontmatter include `PreToolUse`, `PostToolUse`, and `Stop`.

Example (command‑scoped hook):

```yaml
---
description: Deploy to staging with validation
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./scripts/validate-deploy.sh"
          once: true
---
```

## Hook Input (Base)

All hook inputs include:
- `session_id` — unique session identifier
- `transcript_path` — path to session transcript
- `hook_event_name` — event type identifier

## Hook Input (Event‑specific)

**PreToolUse**
- `hook_event_name: "PreToolUse"`
- `tool_name`
- `tool_input`

**PostToolUse**
- `hook_event_name: "PostToolUse"`
- `tool_name`
- `tool_input`
- `tool_response`

**Notification**
- `hook_event_name: "Notification"`
- `message`

**Stop**
- `hook_event_name: "Stop"`
- `stop_hook_active`

**SubagentStop**
- `hook_event_name: "SubagentStop"`
- `stop_hook_active`

**UserPromptSubmit**
- `hook_event_name: "UserPromptSubmit"`
- `prompt`

**PreCompact**
- `hook_event_name: "PreCompact"`
- `trigger`
- `custom_instructions`

## Hook Output (Base)

All hook outputs may include:
- `continue` (boolean) — false to stop processing
- `stopReason` (string)
- `suppressOutput` (boolean)

## Hook Output (Event‑specific)

**PreToolUse output**
- `decision: "approve" | "block"`
- `reason` (shown to user when blocking)

**PostToolUse output**
- `decision: "block"`
- `reason`

**Stop output**
- `decision: "block"`
- `reason`

**SubagentStop output**
- `decision: "block"`
- `reason`

**UserPromptSubmit output**
- `decision: "block"`
- `reason`
- `hookSpecificOutput`  
  - `hookEventName`
  - `additionalContext`

**Notification / PreCompact output**
- Base fields only

## Note

This file reflects the official Claude Code hook reference. Confirm event names and fields against upstream docs if CLI versions change.
