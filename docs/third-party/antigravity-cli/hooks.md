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

Antigravity 1.1.16 documents and embeds only `type`, `command`, and `timeout`
for a command handler. It exposes no `async` or background field, no
`asyncRewake`-style wake field, and no async-output delivery contract. The
presence of runtime background tasks does not establish an asynchronous hook
facility.

`PreInvocation` and `PostInvocation` may synchronously return `injectSteps`,
but no source establishes that a later background completion can inject steps
or start an execution. There is no documented per-event async allowance.

## Common Input

The installed runtime contract also includes `modelName` in every payload.

Observed on CLI 1.4.7, every payload also carries `lastUserInput`; no vendor
document describes it.

Hook commands receive camel-case JSON on standard input. Every event includes `conversationId`, `workspacePaths`, `transcriptPath`, and `artifactDirectoryPath`.

## PreInvocation

`PreInvocation` fires before Antigravity calls the model. Its event-specific input includes:

- `invocationNum`: the zero-based model invocation number; the first invocation is `0`.
- `initialNumSteps`: the number of steps already in the trajectory.

The stdout object may contain `injectSteps`. Each injected step contains exactly one supported shape, including `ephemeralMessage` for transient system context.

The installed contract establishes that `invocationNum` is zero-based, but does
not establish its reset boundary or state owner. It must not be treated as a
per-session or per-turn discriminator without a live payload probe.

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

## PostToolUse

`PostToolUse` fires after a tool completes. The installed contract establishes
the zero-based `stepIdx` and optional `error` as event-specific input. It
requires an empty stdout object:

```json
{}
```

The upstream reference also names `toolCall` for this event, but the installed
contract does not establish that field. Treat its presence as a runtime-version
gap rather than assuming it from the upstream envelope.

## PostInvocation

`PostInvocation` fires immediately after each model invocation completes. It
receives the same event-specific input as `PreInvocation`:

- `invocationNum`: the zero-based model invocation number; the first invocation is `0`.
- `initialNumSteps`: the number of steps already in the trajectory.

The compiled hook protobuf in the installed 1.1.16 binary names `modelOutput`
and `modelThinking` on this payload. The embedded prose contract and upstream
reference do not establish their JSON shapes or semantics.

Its stdout object may contain `injectSteps` with the same `toolCall`,
`userMessage`, and `ephemeralMessage` step shapes as `PreInvocation`, plus an
optional `terminationBehavior`: `force_continue`, `terminate`, or omitted/empty
for the default behavior.

```json
{
  "injectSteps": [],
  "terminationBehavior": "force_continue"
}
```

## Stop

`Stop` fires when an execution loop terminates. Its event-specific input includes `executionNum`, `terminationReason`, `error`, and required `fullyIdle`. `fullyIdle` is true only after the agent and all background or asynchronous work are finished.

`terminationReason` names why the loop ended. On the hook wire it carries the
executor's enumeration in uppercase. The upstream reference's example values
`model_stop` and `max_steps_exceeded` are documentation examples: they are not
emitted and do not occur as enumeration names in the installed executable.
Observed on agy 1.1.27 (2026-09-07): a clean completion arrives as
`terminationReason: "NO_TOOL_CALL"` with `error` empty and `fullyIdle` true; a
provider failure arrives as `terminationReason: "ERROR"` with a non-empty
`error` string (a `RESOURCE_EXHAUSTED (code 429)` quota message in the observed
case). The executable's executor enumerates `early_continue`, `error`,
`halted_step`, `injected_response`, `max_forced_invocations`,
`max_invocations`, `max_token_budget_exceeded`, `no_tool_call`,
`terminal_custom_hook`, `terminal_step_type`, `unspecified`, and
`user_canceled`. `NO_TOOL_CALL`, `ERROR`, `USER_CANCELED`, and `UNSPECIFIED`
are confirmed in uppercase on the wire or in the binary; the remaining
spellings are inferred from that pattern, and no vendor document enumerates
the wire vocabulary.

The failure discriminator is the sibling `error` member, documented as "present
if stopped due to error": it is an empty string on a clean stop and a non-empty
message on a failed one. `fullyIdle` is the idle discriminator. `terminationReason`
is informational; deciding completion from it means guessing at a vocabulary the
vendor neither documents nor stabilizes.

Its stdout object requires a `decision`. `continue` prevents stopping and re-enters the execution loop; any other value permits the stop. When the decision is `continue`, optional `reason` is injected as a system message.

```json
{
  "decision": "continue",
  "reason": "Continue the execution loop"
}
```

## Per-event capability matrix

All rows include the common input fields above. “Context injection” means a
hook response that the installed runtime establishes as reaching a subsequent
model invocation in the active execution loop; a permission decision alone is
not context injection.

| Event            | Additional input fields                                                                                                                     | Context injection                                                                                                                                                                          | Activity signal for UI cadence                                                                                                                                               | Lifecycle discriminator and frequency                                                                                                                                                             |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PreToolUse`     | `toolCall.name`, `toolCall.args`, `stepIdx` (0-based)                                                                                       | No direct model-context output is established. `reason` is shown to the user or agent for the gating decision, but the installed contract does not establish it as injected model context. | Yes: proposed tool-execution activity before state changes.                                                                                                                  | `stepIdx` identifies the trajectory position. Fires for each matching tool call and can repeat within one execution loop.                                                                         |
| `PostToolUse`    | `stepIdx` (0-based); optional `error`. The installed contract does not establish upstream-documented `toolCall`.                            | No: stdout must be `{}`.                                                                                                                                                                   | Yes: completed-tool state signal, including a reported failure when `error` is present.                                                                                      | `stepIdx` identifies the completed trajectory position. Fires for each matching tool completion and can repeat within one execution loop.                                                         |
| `PreInvocation`  | `invocationNum` (0-based; first is `0`); `initialNumSteps`                                                                                  | Yes: `injectSteps[].ephemeralMessage` supplies transient system context; `injectSteps[].userMessage` injects user input. `injectSteps[].toolCall` injects an action, not text context.     | Yes: model-invocation start state, not a streaming output delta.                                                                                                             | `invocationNum` identifies an invocation, but its per-session versus per-turn/execution scope and reset boundary are not established. It cannot distinguish session start from prompt acceptance. |
| `PostInvocation` | `invocationNum` (0-based; first is `0`); `initialNumSteps`; `modelOutput`; `modelThinking` (their shapes and semantics are not established) | Yes: `injectSteps[]` has the same step shapes as `PreInvocation`, after the invocation; `ephemeralMessage` is transient system context.                                                    | Yes: model-invocation completion state. `modelOutput` and `modelThinking` are defined payload members, but no source establishes their serialization or streaming semantics. | `invocationNum` has the same unestablished scope/reset boundary as `PreInvocation`. `terminationBehavior` distinguishes default, forced continuation, and termination.                            |
| `Stop`           | `executionNum`; `terminationReason`; optional `error`; `fullyIdle`                                                                          | Yes, only on continuation: `decision: "continue"` re-enters the loop and `reason` is injected as a system message.                                                                         | Yes: execution-termination state. `fullyIdle` distinguishes a genuinely idle agent from one with background work.                                                            | `executionNum`, `terminationReason`, and `fullyIdle` distinguish the stop position. Fires once per stop attempt and repeats when a continuation re-enters the loop.                               |

The installed runtime exposes no hook event for streamed model-output chunks.
`PreToolUse` and `PostToolUse` supply per-tool cadence; `PreInvocation` and
`PostInvocation` supply per-model-invocation cadence; `Stop` supplies terminal
or continuation state.

`invocationNum` is session-scoped: it counts model invocations across the whole
conversation and does not reset when a turn begins. Only `0` carries a usable
meaning — the session's first invocation. Beyond that the counter cannot
separate a new turn's first invocation from a later invocation inside the same
turn, so it is not a lifecycle discriminator.

`PostInvocation` therefore does what a counter predicate cannot: it fires after
every model invocation, so its firing alone marks the position between a model
response and the next step, with no predicate required.

Stop's `executionNum` is a distinct protobuf field, and the installed binary
does not expose its owner or reset point; its scope is unestablished.

## Sources

- https://antigravity.google/docs/hooks
