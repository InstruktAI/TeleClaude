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
  - Used to pre-inject memory context or domain-baseline instructions via `additionalContext` or `injectSteps`.
- `PreToolUse` → `event_type = "tool_use"`
  - Drives live tool execution indicators in the TeleClaude TUI.
- `Stop` → `event_type = "stop"`
  - Turn completion signal. Triggers checkpoint evaluations and updates `last_message_sent_at` in the database.

## Sources

- https://geminicli.com/docs/hooks
- https://antigravity.google/docs/gcli-migrationks/reference
