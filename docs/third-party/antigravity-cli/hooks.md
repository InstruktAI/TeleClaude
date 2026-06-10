---
description: Antigravity CLI (agy) Hooks and Event Lifecycle
---

# Antigravity CLI (agy) Hooks and Event Lifecycle

## Overview

The Antigravity CLI (`agy`) supports a powerful event hooks framework to execute local command scripts during runtime lifecycle changes. Hooks receive JSON payloads describing the active state via `stdin` and can inject context or command overlays using `stdout`.

## Configuration Model

Unlike the legacy inline `"hooks"` array inside Gemini's settings, `agy` expects a dedicated **`hooks.json`** file in the configuration directory:

- **User Global Hooks**: `~/.gemini/config/hooks.json`
- **Project Local Hooks**: `.agents/hooks.json`

### `hooks.json` Format

The `hooks.json` file groups event handlers under custom user tables (e.g. `"teleclaude"`), which map specific event names to lists of command configuration objects:

```json
{
  "teleclaude": {
    "PreInvocation": [
      {
        "type": "command",
        "command": "/Users/username/Workspace/InstruktAI/TeleClaude/teleclaude/hooks/receiver/__main__.py --agent gemini --cwd \"$PWD\" PreInvocation"
      }
    ],
    "PreToolUse": [
      {
        "type": "command",
        "command": "/Users/username/Workspace/InstruktAI/TeleClaude/teleclaude/hooks/receiver/__main__.py --agent gemini --cwd \"$PWD\" PreToolUse"
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "/Users/username/Workspace/InstruktAI/TeleClaude/teleclaude/hooks/receiver/__main__.py --agent gemini --cwd \"$PWD\" Stop"
      }
    ]
  }
}
```

## Hook Event Lifecycle

The `agy` binary defines this event sequence. There is **no `SessionStart` hook**.
Observed payloads carry `conversationId`, `transcriptPath`, `artifactDirectoryPath`,
and `workspacePaths` — but **not** prompt or assistant text, which must be read from
the transcript:

| Event Name           | Description                                                             | Observed payload fields                                                                               |
| :------------------- | :---------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------- |
| **`PreInvocation`**  | Fires after user submits a prompt but before model inference.           | `conversationId`, `transcriptPath`, `invocationNum`, `initialNumSteps`, `workspacePaths` (no prompt). |
| **`PostInvocation`** | Fires after the model returns a response but before any tool execution. | Not ingested by TeleClaude.                                                                           |
| **`PreToolUse`**     | Fires immediately before a tool is executed.                            | `conversationId`, `transcriptPath`, tool fields.                                                      |
| **`PostToolUse`**    | Fires after a tool executes, capturing results.                         | Not ingested by TeleClaude.                                                                           |
| **`Stop`**           | Fires when the execution turn completely terminates.                    | `conversationId`, `transcriptPath`, `terminationReason`, `fullyIdle` (no assistant message).          |

## TeleClaude Integration & Event Mapping

TeleClaude leverages these hooks to track activities and inject context:

- **`PreInvocation`** $\rightarrow$ `event_type = "user_prompt_submit"`
  - Used to inject dynamic workspace baselines, memory snippets, and custom system overrides via `additionalContext`.
- **`PreToolUse`** $\rightarrow$ `event_type = "tool_use"`
  - Drives live tool usage status lines and loading animations in the TeleClaude TUI.
- **`Stop`** $\rightarrow$ `event_type = "stop"`
  - Signals the completion of the turn, updating session status in the database and triggering checkpoint verification.

## Sources

- https://antigravity.google/docs/hooks
- https://dev.to/google/antigravity-cli-2-0
