---
description: Gemini and Antigravity CLI Hooks
id: third-party/gemini-cli/hooks
scope: project
type: third-party
---

# Gemini and Antigravity CLI Hooks

## Overview

The CLIs execute custom local commands at lifecycle events. Hooks receive JSON payloads describing the event via `stdin` and can inject instructions or respond via `stdout`.

## Configuration Models

- **Legacy Gemini**: Configured inline within `settings.json` under the `"hooks"` key.
- **Antigravity CLI (`agy`)**: Configured in a dedicated **`hooks.json`** file in the customization directory:
  - **User Global**: `~/.gemini/config/hooks.json`
  - **Project Local**: `.agents/hooks.json`

### `hooks.json` Schema Format

The root key of `hooks.json` holds a user/identifier table (e.g. `"teleclaude"`), which maps specific event names to lists of command configuration objects:

```json
{
  "teleclaude": {
    "PreInvocation": [
      {
        "type": "command",
        "command": "/Users/username/Workspace/InstruktAI/TeleClaude/teleclaude/hooks/receiver/__main__.py --agent agy --cwd \"$PWD\" PreInvocation"
      }
    ],
    "PreToolUse": [
      {
        "type": "command",
        "command": "/Users/username/Workspace/InstruktAI/TeleClaude/teleclaude/hooks/receiver/__main__.py --agent agy --cwd \"$PWD\" PreToolUse"
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "/Users/username/Workspace/InstruktAI/TeleClaude/teleclaude/hooks/receiver/__main__.py --agent agy --cwd \"$PWD\" Stop"
      }
    ]
  }
}
```

## Hook Event Comparison

| Legacy Gemini Event | Antigravity (`agy`) Event | Description |
| :--- | :--- | :--- |
| **`SessionStart`** | — | Fires when a session begins |
| **`BeforeAgent`** | **`PreInvocation`** | Fires after user submits prompt, before planning/model call |
| — | **`PostInvocation`** | Fires after the model returns but before tools execute |
| **`BeforeTool`** | **`PreToolUse`** | Fires before a tool executes (drives TUI activity) |
| **`AfterTool`** | **`PostToolUse`** | Fires after a tool finishes |
| **`AfterAgent`** | **`Stop`** | Fires when the execution loop terminates (turn completion) |

## TeleClaude Adapter Mapping

TeleClaude installs hooks to intercept lifecycle events. Below is the mapping between native events and TeleClaude's internal hook representation:

### Legacy Gemini Mapping

- `SessionStart` → `event_type = "session_start"`
- `BeforeAgent` → `event_type = "user_prompt_submit"`
- `BeforeTool` → `event_type = "tool_use"` (drives TUI activity)
- `AfterAgent` → `event_type = "stop"` (turn completion)

### Antigravity CLI (`agy`) Mapping

- `PreInvocation` → `event_type = "user_prompt_submit"`
- `PreToolUse` → `event_type = "tool_use"` (drives live tool indicators in the TUI)
- `Stop` → `event_type = "agent_stop"` (turn completion; triggers checkpoint evaluation)

### Synthetic session_start

`agy` exposes **no** `SessionStart` hook — a conversation opens with `PreInvocation`.
TeleClaude therefore synthesizes an internal `session_start` from the first activity
event of an unbound conversation (see `AgyAdapter.synthesizes_session_start` and the
receiver's `_maybe_synthesize_session_start`). The synthetic event creates/binds the
session row and runs the normal session-start machinery before the activity event is
processed.

### Payload schema (observed)

`agy` hook payloads use non-canonical field names and **carry no prompt/assistant
text** — that content is read from the transcript by the projection layer. The
`AgyAdapter.normalize_payload` maps `conversationId → session_id` and
`transcriptPath → transcript_path`.

`PreInvocation`:

```json
{
  "conversationId": "<uuid>",
  "artifactDirectoryPath": "~/.gemini/antigravity-cli/brain/<uuid>",
  "transcriptPath": "~/.gemini/antigravity-cli/brain/<uuid>/.system_generated/logs/transcript.jsonl",
  "initialNumSteps": 1,
  "invocationNum": 0,
  "workspacePaths": ["<cwd>"]
}
```

`Stop`:

```json
{
  "conversationId": "<uuid>",
  "transcriptPath": "<path>",
  "error": "",
  "executionNum": 0,
  "fullyIdle": true,
  "terminationReason": "NO_TOOL_CALL",
  "workspacePaths": ["<cwd>"]
}
```

`conversationId` doubles as the `agy --conversation <id>` resume identifier. The
payload shapes above were captured from the `agy` runtime — Google's published docs
do not yet document hook payload schemas.

## Sources

- https://antigravity.google/docs/hooks
- https://geminicli.com/docs/hooks
