---
description: 'SUPERSEDED by Antigravity CLI (agy) — legacy Gemini CLI reference only. Gemini and Antigravity CLI Hooks'
---

# Gemini and Antigravity CLI Hooks

> **Superseded.** The legacy Node-based Gemini CLI is obsolete; the Antigravity CLI
> (`agy`) replaces it — see `third-party/antigravity-cli/hooks` for the current contract.
> This document is retained as a migration reference for the legacy layout only; do not
> treat its paths or flags as current. TeleClaude still provisions some legacy Gemini
> paths; migrating that provisioning to the `agy` layout is in flight.

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

| Legacy Gemini Event | Antigravity (`agy`) Event | Description                                                 |
| :------------------ | :------------------------ | :---------------------------------------------------------- |
| **`SessionStart`**  | —                         | Fires when a session begins                                 |
| **`BeforeAgent`**   | **`PreInvocation`**       | Fires after user submits prompt, before planning/model call |
| —                   | **`PostInvocation`**      | Fires after the model returns but before tools execute      |
| **`BeforeTool`**    | **`PreToolUse`**          | Fires before a tool executes (drives TUI activity)          |
| **`AfterTool`**     | **`PostToolUse`**         | Fires after a tool finishes                                 |
| **`AfterAgent`**    | **`Stop`**                | Fires when the execution loop terminates (turn completion)  |
| **`Notification`**  | —                         | Fires when Gemini CLI emits a system alert                  |

Legacy Gemini `Notification` payload fields are:

- `notification_type` (`ToolPermission` is the currently documented value)
- `message` (alert summary)
- `details` (alert-specific JSON metadata)

The hook is observability-only. It cannot block an alert or grant permission.

## TeleClaude Adapter Mapping

TeleClaude installs hooks to intercept lifecycle events. Below is the mapping between native events and TeleClaude's internal hook representation:

### Legacy Gemini Mapping

- `SessionStart` → `event_type = "session_start"`
- `BeforeAgent` → `event_type = "user_prompt_submit"`
- `BeforeTool` → `event_type = "tool_use"` (drives TUI activity)
- `AfterAgent` → `event_type = "stop"` (turn completion)
- `Notification` is not catalogued or installed by TeleClaude.

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

## Human-attention integration boundary

Gemini CLI also has an experimental terminal notification feature, separate from
the hook contract. It emits OSC 9 (falling back to BEL) for `Action required`
when the model waits for user input or tool approval, and for `Session complete`.
The documented `Notification` hook is narrower: its only specified type is
`ToolPermission`. The terminal feature therefore proves that Gemini knows about
general input-wait states, but the public hook schema does not yet promise those
states as structured hook payloads.

TeleClaude can consume the native `Notification` hook for tool permission. General
human-input requests need either a future documented Gemini hook type or an explicit
first-class TeleClaude request invocation. It must not infer the request from
transcript text, terminal escape sequences, or a bell.

## Sources

- https://antigravity.google/docs/hooks
- https://geminicli.com/docs/hooks/reference/
- https://geminicli.com/docs/cli/notifications/
