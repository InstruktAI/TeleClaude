# Claude Code Hooks — Input/Output Shapes

Source: Claude Code Hook SDK (community reference).  
Origin: context7.com/mizunashi-mana/claude-code-hook-sdk/llms.txt  
Last Updated: 2026-01-15

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

This is a community SDK reference for hook payload shapes. Confirm any provider‑specific details against official CLI docs when available.
