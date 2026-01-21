# Gemini CLI Hooks — Input/Output Shapes

Source: Gemini CLI official docs (hooks reference).  
Origin: github.com/google-gemini/gemini-cli/docs/hooks/reference.md  
Last Updated: 2026-01-15

## Hook Input (Base)

All hook inputs include:

- `session_id`
- `transcript_path`
- `cwd`
- `hook_event_name`
- `timestamp`

## Hook Input (Event‑specific)

**Tool Events (`BeforeTool`, `AfterTool`)**

- `tool_name`
- `tool_input`
- `tool_response` (AfterTool only)

**Agent Events (`BeforeAgent`, `AfterAgent`)**

- `prompt`
- `prompt_response` (AfterAgent only)
- `stop_hook_active` (AfterAgent only)

**Model Events (`BeforeModel`, `AfterModel`, `BeforeToolSelection`)**

- `llm_request`
- `llm_response` (AfterModel only)

**Session/Notification Events**

- `source` (SessionStart only)
- `reason` (SessionEnd only)
- `trigger` (PreCompress only)
- `notification_type`, `message`, `details` (Notification only)

## Hook Output (Common)

If the hook exits with `0`, stdout is parsed as JSON.

Common fields:

- `decision` — `allow | deny | block | ask | approve`
- `reason` — shown to the agent when blocking/denying
- `systemMessage` — shown to the user in CLI
- `continue` — `false` terminates the agent loop for this turn
- `stopReason`
- `suppressOutput`
- `hookSpecificOutput` — event‑specific data

## Context Injection (BeforeAgent)

Hook can inject additional context using:

```json
{
  "decision": "allow|deny",
  "hookSpecificOutput": {
    "hookEventName": "BeforeAgent",
    "additionalContext": "Recent project decisions: ..."
  }
}
```

## Exit Codes (Fallback Behavior)

- Exit `0` → allow (stdout processed)
- Exit `2` → deny (stderr shown to agent)
- Other → warning (logged, continues)

## Note

This is based on official Gemini CLI hook docs. Confirm event names and fields against upstream docs if CLI versions change.
