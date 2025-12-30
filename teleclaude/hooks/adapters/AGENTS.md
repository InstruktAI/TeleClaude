# Hook event references

This directory contains adapters that normalize hook payloads into TeleClaude's
agent hook event schema. The schemas below are the source of truth and should
be followed directly (no guessing).

## Gemini CLI hooks

| Event               | When It Fires                                 | Common Use Cases                           |
| ------------------- | --------------------------------------------- | ------------------------------------------ |
| SessionStart        | When a session begins                         | Initialize resources, load context         |
| SessionEnd          | When a session ends                           | Clean up, save state                       |
| BeforeAgent         | After user submits prompt, before planning    | Add context, validate prompts              |
| AfterAgent          | When agent loop ends                          | Review output, force continuation          |
| BeforeModel         | Before sending request to LLM                 | Modify prompts, add instructions           |
| AfterModel          | After receiving LLM response                  | Filter responses, log interactions         |
| BeforeToolSelection | Before LLM selects tools (after BeforeModel)  | Filter available tools, optimize selection |
| BeforeTool          | Before a tool executes                        | Validate arguments, block dangerous ops    |
| AfterTool           | After a tool executes                         | Process results, run tests                 |
| PreCompress         | Before context compression                    | Save state, notify user                    |
| Notification        | When a notification occurs (e.g., permission) | Auto-approve, log decisions                |

Sources:

- https://geminicli.com/docs/hooks/
- https://geminicli.com/docs/hooks/reference/

## Gemini hook input contract (selected fields we use)

Base fields (all events):

- `session_id` (string)
- `transcript_path` (string, if available)
- `cwd` (string)
- `hook_event_name` (string)
- `timestamp` (string, ISO 8601)

SessionStart fields:

- `source` (`startup` | `resume` | `clear`)

SessionEnd fields:

- `reason` (`exit` | `clear` | `logout` | `prompt_input_exit` | `other`)

Notification fields:

- `notification_type` (`ToolPermission`)
- `message` (string)
- `details` (object)

## TeleClaude adapter mapping (Gemini → internal hook payloads)

TeleClaude only consumes a **subset** of hook events and forwards them as
`teleclaude__handle_agent_event` with the following internal shape:

```
{
  "session_id": "<teleclaude_session_id>",
  "event_type": "session_start|stop|session_end|notification",
  "data": { ...original hook payload... }
}
```

Mapping rules (Gemini):

- `SessionStart` → `event_type = "session_start"`
  - Requires `data.session_id` (native session id).
  - Requires `data.transcript_path` (native transcript path).
- `AfterAgent` → `event_type = "stop"` (fires when agent loop ends = turn completion)
- `Notification` → `event_type = "notification"`
- `SessionEnd` → `event_type = "session_end"` (reserved; no handler logic yet)

Note: `BeforeUserInput` does NOT exist in Gemini CLI. Use `AfterAgent` for turn completion.

## Internal typed payloads

TeleClaude now uses typed internal payload models (see `teleclaude/core/events.py`):

- `AgentSessionStartPayload`
- `AgentStopPayload`
- `AgentNotificationPayload`
- `AgentSessionEndPayload` (reserved)

These are constructed in `teleclaude/core/adapter_client.py` and enforced via
direct field access (no `.get` fallbacks for required fields).

## Claude Code hooks

Claude Code provides several hook events that run at different points in the workflow:

- PreToolUse: Runs before tool calls (can block them)
- PermissionRequest: Runs when a permission dialog is shown (can allow or deny)
- PostToolUse: Runs after tool calls complete
- UserPromptSubmit: Runs when the user submits a prompt, before Claude processes it
- Notification: Runs when Claude Code sends notifications
- Stop: Runs when Claude Code finishes responding
- SubagentStop: Runs when subagent tasks complete
- PreCompact: Runs before Claude Code is about to run a compact operation
- SessionStart: Runs when Claude Code starts a new session or resumes an existing session
- SessionEnd: Runs when Claude Code session ends

Sources:

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/hooks-guide#hook-events-overview

## Claude hook input contract (selected fields we use)

Base fields (all events):

- `session_id` (string)
- `transcript_path` (string)
- `cwd` (string)
- `permission_mode` (string: `default`, `plan`, `acceptEdits`, `bypassPermissions`)
- `hook_event_name` (string)

SessionStart fields:

- `source` (`startup`)

SessionEnd fields:

- `reason` (`exit`)

Notification fields:

- `message` (string)
- `notification_type` (`permission_prompt`)

## TeleClaude adapter mapping (Claude → internal hook payloads)

Mapping rules (Claude):

- `SessionStart` → `event_type = "session_start"`
  - Requires `data.session_id` (native session id).
  - Requires `data.transcript_path` (native transcript path).
- `Stop` → `event_type = "stop"`
- `Notification` → `event_type = "notification"`
- `SessionEnd` → `event_type = "session_end"` (reserved; no handler logic yet)

## Summary enrichment (internal)

Adapters never enrich payloads. The daemon enriches `stop` events by running
summarization against the transcript markdown produced by
`teleclaude/utils/transcript.py` (see `parse_session_transcript(...)`).
