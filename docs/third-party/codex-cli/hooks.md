---
description: Codex Hooks
---

# Codex Hooks

## Overview

Codex CLI exposes a native hook surface that runs local commands at lifecycle
events. Hooks receive JSON on stdin and may produce JSON or text on stdout to
influence Codex's next action.

Codex 0.166.0 (`HookEventName` in `codex-rs/protocol/src/protocol.rs`) supports
fourteen native hook events:

- `SessionStart`
- `SessionEnd`
- `SubagentStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse`
- `PreCompact`
- `PostCompact`
- `SubagentStop`
- `Stop`
- `Interrupt`
- `PreModelRequest` (since 0.164.0)
- `PostModelRequest` (since 0.164.0)

## Configuration

### Hooks discovery

Codex resolves hook configuration from these locations:

- `~/.codex/hooks.json`
- `~/.codex/config.toml` (`[hooks]` table)
- `<repo>/.codex/hooks.json`
- `<repo>/.codex/config.toml`

### Feature flag

The native hooks runtime is configured in `~/.codex/config.toml`. A configuration
that explicitly enables it has this shape:

```toml
[features]
hooks = true
```

In Codex 0.129+ the `hooks` feature is `Stage::Stable` with `default_enabled = true`,
so the explicit flag is belt-and-suspenders. `hooks` is the canonical key and
`codex_hooks` remains a deprecated alias.

### Background command hooks

Set `async: true` on a command handler (`"async": true` in `hooks.json` or
`async = true` in inline TOML). Codex continues immediately, but the hook keeps
the same input, matcher, trust review, timeout, and output handling as its
synchronous counterpart.

Background hooks retain supported informational output. On completion, Codex
adds `additionalContext` to model context and surfaces `systemMessage` as a
warning at the next safe point: in an active turn, after the current model
request and tool calls complete, before the next model request in that turn;
otherwise, on the next user turn. Completion does not start a turn. A
background hook cannot block, approve, rewrite, or otherwise control its
triggering operation.

The per-event output contract still limits the usable channel. In particular,
`SessionEnd` is always synchronous and its advisory output cannot steer Codex.
Codex documents no `asyncRewake` equivalent. `statusMessage` is a separate
optional handler field, not a documented wake-up or model-injection mechanism.

### Matcher syntax

`matcher` is a regex string applied to a specific field per event.

| Event               | Matcher applies to | Example                     |
| ------------------- | ------------------ | --------------------------- |
| `SessionStart`      | `source`           | `"startup\|resume"`         |
| `SessionEnd`        | `reason`           | `"other"`                   |
| `SubagentStart`     | `agent_type`       | `"worker"`                  |
| `SubagentStop`      | `agent_type`       | `"worker"`                  |
| `PreToolUse`        | `tool_name`        | `"Bash"`, `"^apply_patch$"` |
| `PostToolUse`       | `tool_name`        | `"Edit\|Write"`             |
| `PermissionRequest` | `tool_name`        | `"mcp__filesystem__.*"`     |
| `PreCompact`        | `trigger`          | `"manual\|auto"`            |
| `PostCompact`       | `trigger`          | `"manual\|auto"`            |
| `UserPromptSubmit`  | not used           | (ignored if present)        |
| `Stop`              | not used           | (ignored if present)        |

## Hook payload contract

### Common input fields (every event)

```json
{
  "session_id": "string",
  "transcript_path": "string | null",
  "cwd": "string",
  "hook_event_name": "string",
  "model": "string"
}
```

`permission_mode` is also present on `SessionStart`, `SubagentStart`,
`PreToolUse`, `PermissionRequest`, `PostToolUse`, `UserPromptSubmit`,
`SubagentStop`, and `Stop`. Its values are `default`, `acceptEdits`, `plan`,
`dontAsk`, and `bypassPermissions`.

The event table below lists every event-specific field. `turn_id` is present on
every event except `SessionStart` and `SessionEnd`.

### Per-event payloads

`SessionStart`:

```json
{
  "source": "startup | resume | clear | compact",
  "session_id": "string",
  "transcript_path": "string | null",
  "cwd": "string",
  "hook_event_name": "string",
  "model": "string"
}
```

`UserPromptSubmit`:

```json
{
  "turn_id": "string",
  "prompt": "string",
  "session_id": "string",
  "transcript_path": "string | null",
  "cwd": "string",
  "hook_event_name": "string",
  "model": "string"
}
```

`PreToolUse`:

```json
{
  "turn_id": "string",
  "tool_name": "string",
  "tool_use_id": "string",
  "tool_input": "JSON value",
  "session_id": "string",
  "transcript_path": "string | null",
  "cwd": "string",
  "hook_event_name": "string",
  "model": "string"
}
```

`PermissionRequest`:

```json
{
  "turn_id": "string",
  "tool_name": "string",
  "tool_input": "JSON value",
  "tool_input.description": "string | null",
  "session_id": "string",
  "transcript_path": "string | null",
  "cwd": "string",
  "hook_event_name": "string",
  "model": "string"
}
```

`PostToolUse`:

```json
{
  "turn_id": "string",
  "tool_name": "string",
  "tool_use_id": "string",
  "tool_input": "JSON value",
  "tool_response": "JSON value",
  "session_id": "string",
  "transcript_path": "string | null",
  "cwd": "string",
  "hook_event_name": "string",
  "model": "string"
}
```

In Codex 0.157.1, `PostToolUse` fires only for a tool call that succeeded: the
tool registry runs post-tool hooks behind the call's success result, so a failed
call emits no `PostToolUse` and there is no failure variant of the event. The
schema of `tool_response` is tool-specific and not published; the event's
presence is the success signal. `apply_patch` is reported with `tool_name`
`apply_patch` (matcher aliases `Write` and `Edit`) and
`tool_input: {"command": "<patch text>"}`.

`Stop`:

```json
{
  "turn_id": "string",
  "stop_hook_active": "boolean",
  "last_assistant_message": "string | null",
  "session_id": "string",
  "transcript_path": "string | null",
  "cwd": "string",
  "hook_event_name": "string",
  "model": "string"
}
```

`Stop` is the only terminal turn event; no failure counterpart exists in
`HookEventName`. In Codex 0.166.0 a turn that ends on an error does not run the
stop hooks: the error branches in `codex-rs/core/src/session/turn.rs` call
`emit_turn_error_lifecycle`, send an `Error` event and leave the turn loop,
while `run_turn_stop_hooks` runs only on the successful no-follow-up path. Such
a turn fires no `Stop`, no `Interrupt` and no legacy `notify`
(`agent-turn-complete`); upstream tracks this as open bug
[`openai/codex#54884`](https://github.com/openai/codex/issues/54884), reproduced
on 0.163.0. The Codex TUI itself shows the error and emits
`OSC 7501;state=idle:app=codex`. A killed process also emits nothing.

`Interrupt` adds `turn_id` and `permission_mode`. Upstream discussion
(`openai/codex#45977`) describes it as covering an Esc interrupt; its trigger
points are not verified here.

`PreModelRequest` and `PostModelRequest` are observation-only: their output
cannot veto a request or alter model context
([`openai/codex#55144`](https://github.com/openai/codex/pull/55144)). Both fire
around every model request attempt, retries included, and add `turn_id` and,
for a subagent, `agent_id` and `agent_type`. `PostModelRequest` also carries:

```json
{
  "status": "completed | failed | cancelled",
  "error": "string | null",
  "token_usage": "{input_tokens, cached_input_tokens, cache_write_input_tokens, output_tokens, reasoning_output_tokens, total_tokens} | null"
}
```

A provider error therefore surfaces as `PostModelRequest` with
`status: "failed"` and the error text. Because a retried attempt fires its own
`PreModelRequest`, a failed attempt is not by itself the end of the turn: a turn
that died on a provider error is a failed `PostModelRequest` that no further
attempt follows. No hook states that the turn ended.

`SessionEnd` adds `reason: "other"`. It has no `turn_id`, does not run for
subagents, and is advisory: its output cannot steer Codex or keep the session
open.

`SubagentStart` adds `turn_id`, `agent_id`, and `agent_type`.

`PreCompact` and `PostCompact` each add `turn_id` and
`trigger: "manual | auto"`.

`SubagentStop` adds `turn_id`, `agent_id`, `agent_type`,
`agent_transcript_path: "string | null"`, `stop_hook_active: boolean`, and
`last_assistant_message: "string | null"`.

## Per-event capability matrix

All rows include the common input fields above. "Context injection" means
content added to model context, not a UI-only `systemMessage` or a block/
continuation decision. An activity signal is scoped to the event's lifecycle
position; it is not a streaming-output signal.

| Event               | Additional input fields                                                                                                       | Context injection                                                                                                                                                                      | Activity signal for UI cadence                                                   | Lifecycle discriminator / frequency                                                                                                 |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `SessionStart`      | `source` (`startup`, `resume`, `clear`, `compact`); `permission_mode`                                                         | Yes: plain stdout or `hookSpecificOutput.additionalContext`, added as developer context.                                                                                               | Session-start state only, not assistant output.                                  | `source` distinguishes startup, resume, clear, and compact. A compact start can occur before an immediate in-turn continuation.     |
| `SessionEnd`        | `reason` (currently `other`)                                                                                                  | No; advisory output cannot steer Codex.                                                                                                                                                | Terminal session-state signal only, not assistant output.                        | `reason` is the only discriminator. The upstream reference gives no cadence counter or idle flag.                                   |
| `SubagentStart`     | `turn_id`, `agent_id`, `agent_type`, `permission_mode`                                                                        | Yes: plain stdout or `hookSpecificOutput.additionalContext`, added as developer context for that subagent.                                                                             | Subagent-start state signal.                                                     | `agent_type` distinguishes the subagent profile. No counter or idle flag is provided.                                               |
| `PreToolUse`        | `turn_id`, `tool_name`, `tool_use_id`, `tool_input`, `permission_mode`                                                        | Yes: `hookSpecificOutput.additionalContext`.                                                                                                                                           | Tool-attempt signal; the tool has not run yet.                                   | `tool_use_id` identifies this invocation. Fires for each eligible local tool call, so it can repeat within one assistant message.   |
| `PermissionRequest` | `turn_id`, `tool_name`, `tool_input`, optional `tool_input.description`, `permission_mode`                                    | No `additionalContext` output field.                                                                                                                                                   | Approval-wait state signal, not tool completion.                                 | `tool_name` identifies the pending request. It occurs only for calls requiring approval; no counter or idle flag is provided.       |
| `PostToolUse`       | `turn_id`, `tool_name`, `tool_use_id`, `tool_input`, `tool_response`, `permission_mode`                                       | Yes: `hookSpecificOutput.additionalContext`, added as developer context after the tool already ran.                                                                                    | Completed eligible-tool signal; its result can represent changed state.          | `tool_use_id` identifies this invocation. Fires for each eligible local tool result, so it can repeat within one assistant message. |
| `PreCompact`        | `turn_id`, `trigger` (`manual`, `auto`)                                                                                       | No.                                                                                                                                                                                    | Pending compaction state only, not assistant output.                             | `trigger` distinguishes manual from automatic compaction; no counter or idle flag is provided.                                      |
| `PostCompact`       | `turn_id`, `trigger` (`manual`, `auto`)                                                                                       | No.                                                                                                                                                                                    | Completed compaction state only, not assistant output.                           | `trigger` distinguishes manual from automatic compaction; no counter or idle flag is provided.                                      |
| `UserPromptSubmit`  | `turn_id`, `prompt`, `permission_mode`                                                                                        | **Yes:** plain stdout or `hookSpecificOutput.additionalContext`, added as extra developer context before the model processes the user prompt.                                          | User-input signal, not an agent-output or state-change signal.                   | The payload has no counter or idle flag. A configured matcher is ignored.                                                           |
| `SubagentStop`      | `turn_id`, `agent_id`, `agent_type`, `agent_transcript_path`, `stop_hook_active`, `last_assistant_message`, `permission_mode` | No. `decision: "block"` with `reason` requests subagent continuation instead.                                                                                                          | Subagent-stop signal; `last_assistant_message` may carry its latest output.      | `stop_hook_active` distinguishes a stop already continued by this hook. It is not an idle flag or a sequence counter.               |
| `Stop`              | `turn_id`, `stop_hook_active`, `last_assistant_message`, `permission_mode`                                                    | **No.** There is no `hookSpecificOutput.additionalContext` field. `decision: "block"` plus `reason` creates a new continuation user prompt; it is not injection into the running turn. | Main-agent stop signal; `last_assistant_message` may carry the completed output. | `stop_hook_active` distinguishes a turn already continued by `Stop`. It is not an idle flag or a sequence counter.                  |

Codex exposes no generic per-message activity counter, idle indicator, or
streaming-text delta. For cadence, `PreToolUse` and `PostToolUse` are the only
events explicitly tied to every eligible local tool call; `PermissionRequest`
is tied to each approval request. The remaining hooks expose a lifecycle
transition, not recurring model-output progress.

## Subagent identification

Codex exposes dedicated `SubagentStart` and `SubagentStop` events. Both carry
`turn_id`, `agent_id`, and `agent_type`; `SubagentStop` additionally carries
`agent_transcript_path`, `stop_hook_active`, and `last_assistant_message`.
The shared `session_id` is the parent Codex session ID.

## Stdout / exit code semantics

| Exit code | Stdout      | Effect                                 |
| --------- | ----------- | -------------------------------------- |
| `0`       | valid JSON  | Codex parses and applies the response  |
| `0`       | empty       | success, execution continues           |
| `2`       | stderr text | block/denial with the stderr as reason |

### Block / decision shapes

`PreToolUse` block:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "string"
  }
}
```

`PreToolUse` can also inject model-visible context without blocking:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "string"
  }
}
```

`PermissionRequest` allow/deny:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PermissionRequest",
    "decision": {
      "behavior": "allow | deny",
      "message": "string"
    }
  }
}
```

`UserPromptSubmit` block:

```json
{ "decision": "block", "reason": "string" }
```

`PostToolUse` feedback (command has already executed; feedback only):

```json
{
  "decision": "block",
  "reason": "string",
  "hookSpecificOutput": {
    "hookEventName": "PostToolUse",
    "additionalContext": "string"
  }
}
```

`Stop` continuation — `decision: "block"` does _not_ reject the turn; it tells
Codex to continue, using `reason` as the continuation prompt:

```json
{ "decision": "block", "reason": "string" }
```

### Common output fields

`SessionStart`, `PreCompact`, `PostCompact`, `UserPromptSubmit`, `SubagentStop`,
and `Stop` accept:

```json
{
  "continue": "boolean",
  "stopReason": "string (optional)",
  "systemMessage": "string (optional)",
  "suppressOutput": "boolean"
}
```

All events support `systemMessage`. `PreToolUse` and `PermissionRequest` do not
support `continue`, `stopReason`, or `suppressOutput`.

## Trust gate (Codex 0.129+)

Codex 0.129 added a per-hook trust requirement (PR
[`openai/codex#20321`](https://github.com/openai/codex/pull/20321)). Hooks
discovered from `~/.codex/hooks.json` are `User`-layer (unmanaged) and stay out
of the runnable handler set until `~/.codex/config.toml` carries a matching
`trusted_hash` for each handler. Without that entry codex silently drops the
handler — no log, no warning beyond a one-line startup banner.

Persisted shape:

```toml
[hooks.state."<key>"]
trusted_hash = "sha256:<hex>"
enabled = true   # optional; user toggle from /hooks
```

Where `<key>` is `{abs_hooks_json_path}:{event_label}:{group_index}:{handler_index}`
and `event_label` is the snake-cased name (`session_start`, `user_prompt_submit`,
`stop`, …).

`trusted_hash` is a SHA-256 of the canonical JSON representation of the
normalized hook identity. Codex's algorithm
(`codex-rs/hooks/src/engine/discovery.rs::command_hook_hash` +
`codex-rs/config/src/fingerprint.rs::version_for_toml`):

1. Build `{ event_name, matcher, hooks: [normalized_handler] }`.
2. Force `matcher` to `None` for `UserPromptSubmit` and `Stop`. Keep the
   configured matcher for `SessionStart` and the tool/compact events.
3. Normalize `timeout` to `Some(timeout_sec.unwrap_or(600).max(1))`.
4. Convert struct → TOML value → JSON value. None-typed fields drop out.
5. Recursively sort object keys (canonical JSON), serialize compactly, hash,
   prefix with `sha256:`.

## Sources

- https://learn.chatgpt.com/docs/hooks
- https://github.com/openai/codex/pull/20321
- https://github.com/openai/codex/blob/rust-v0.157.1/codex-rs/core/src/tools/registry.rs
- https://github.com/openai/codex/blob/rust-v0.157.1/codex-rs/core/src/tools/handlers/apply_patch.rs
- https://github.com/openai/codex/blob/rust-v0.157.1/codex-rs/core/src/tools/hook_names.rs
- https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/protocol/src/protocol.rs
- https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/core/src/session/turn.rs
- https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/hooks/src/schema.rs
- https://github.com/openai/codex/blob/rust-v0.166.0/codex-rs/hooks/schema/generated/model-request.command.input.schema.json
- https://github.com/openai/codex/pull/55144
- https://github.com/openai/codex/issues/54884
- https://github.com/openai/codex/issues/45977
