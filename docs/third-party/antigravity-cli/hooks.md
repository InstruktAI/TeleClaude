---
description: Google Antigravity hook configuration, lifecycle payloads, and stdout contracts
---

# Google Antigravity Hooks

## Configuration

Antigravity reads hooks from a dedicated `hooks.json` customization file. Workspace hooks live at `.agents/hooks.json`; global hooks live under `~/.gemini/config/`.

The file maps a caller-defined hook group to native event names. `PreInvocation`, `PostInvocation`, and `Stop` contain command handlers directly. `PreToolUse` and `PostToolUse` instead contain matcher groups, and each matcher group owns a nested `hooks` array.

```json
{
  "teleclaude": {
    "PreInvocation": [
      {
        "type": "command",
        "command": "hook-receiver PreInvocation"
      }
    ],
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "hook-receiver PreToolUse"
          }
        ]
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "hook-receiver Stop"
      }
    ]
  }
}
```

`matcher` is a regular expression over the tool name for tool events. `""` and `"*"` match every tool. A command handler may declare `type`, `command`, and `timeout`; `command` is required, `type` defaults to `command`, and `timeout` defaults to 30 seconds.

## Background execution

Antigravity 1.1.15 documents and embeds only `type`, `command`, and `timeout`
for a command handler. It exposes no `async` or background field, no
`asyncRewake`-style wake field, and no async-output delivery contract. The
presence of runtime background tasks does not establish an asynchronous hook
facility.

`PreInvocation` and `PostInvocation` may synchronously return `injectSteps`,
but no source establishes that a later background completion can inject steps
or start an execution. There is no documented per-event async allowance.

## Common Input

Hook commands receive camel-case JSON on standard input. Every event includes `conversationId`, `workspacePaths`, `transcriptPath`, and `artifactDirectoryPath`.

## PreInvocation

`PreInvocation` fires before Antigravity calls the model. Its event-specific input includes:

- `invocationNum`: the zero-based model invocation number; the first invocation is `0`.
- `initialNumSteps`: the number of steps already in the trajectory.

The stdout object may contain `injectSteps`. Each injected step contains exactly one supported shape, including `ephemeralMessage` for transient system context.

```json
{
  "injectSteps": [
    {
      "ephemeralMessage": "Transient context"
    }
  ]
}
```

An empty object is a valid response when no steps are injected.

## PreToolUse

`PreToolUse` fires before a tool executes. Its event-specific input includes `toolCall.name`, `toolCall.args`, and the zero-based `stepIdx`.

Its stdout object requires a `decision`: `allow`, `deny`, `ask`, or `force_ask`. `reason` and `permissionOverrides` are optional.

```json
{
  "decision": "allow"
}
```

## Stop

`Stop` fires when an execution loop terminates. Its event-specific input includes `executionNum`, `terminationReason`, optional `error`, and required `fullyIdle`. `fullyIdle` is true only after the agent and all background or asynchronous work are finished.

Its stdout object requires a `decision`. `continue` prevents stopping and re-enters the execution loop; any other value permits the stop. When the decision is `continue`, optional `reason` is injected as a system message.

```json
{
  "decision": "continue",
  "reason": "Continue the execution loop"
}
```

## Sources

- https://antigravity.google/docs/hooks
