---
description: Codex Hooks
---

# Codex Hooks

## Overview

Codex CLI exposes a native hook surface that runs local commands at lifecycle
events. Hooks receive JSON on stdin and may produce JSON or text on stdout to
influence Codex's next action.

Six native hook events are supported upstream:

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse`
- `Stop`

## Configuration

### Hooks discovery

Codex resolves hook configuration from these locations:

- `~/.codex/hooks.json`
- `~/.codex/config.toml` (`[hooks]` table)
- `<repo>/.codex/hooks.json`
- `<repo>/.codex/config.toml`

### Feature flag

The native hooks runtime is gated by `~/.codex/config.toml`. Upstream documentation
references the flag name `codex_hooks`. The flag name has shifted across Codex
versions; current TeleClaude installs write:

```toml
[features]
hooks = true
```

In Codex 0.129+ the `hooks` feature is `Stage::Stable` with `default_enabled = true`,
so the explicit flag is belt-and-suspenders. Verify against your installed Codex
version if hooks are not firing.

### Matcher syntax

`matcher` is a regex string applied to a specific field per event.

| Event               | Matcher applies to | Example                     |
| ------------------- | ------------------ | --------------------------- |
| `SessionStart`      | `source`           | `"startup\|resume"`         |
| `PreToolUse`        | `tool_name`        | `"Bash"`, `"^apply_patch$"` |
| `PostToolUse`       | `tool_name`        | `"Edit\|Write"`             |
| `PermissionRequest` | `tool_name`        | `"mcp__filesystem__.*"`     |
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

Turn-scoped hooks (`PreToolUse`, `PermissionRequest`, `PostToolUse`,
`UserPromptSubmit`, `Stop`) add a `turn_id` field.

### Per-event payloads

`SessionStart`:

```json
{
  "source": "startup | resume | clear",
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

## Subagent identification

**The native hook payload does not expose any subagent linkage.** There is no
`parent_session_id`, `parent_thread_id`, or `subagent_id` field, and there are
no dedicated subagent hook events. When Codex spawns a thread subagent the
spawned thread emits the _same_ hook events (`SessionStart`, `UserPromptSubmit`,
`Stop`, …) under its own `session_id`.

To distinguish subagent events from root-session events, the transcript file
must be inspected. The first line of a Codex transcript is a `session_meta`
record whose payload carries the parent linkage when present:

```jsonc
{
  "type": "session_meta",
  "payload": {
    "id": "<thread_id>",
    "source": {
      "subagent": {
        "thread_spawn": {
          "parent_thread_id": "<parent_thread_id>",
        },
      },
    },
  },
}
```

Presence of `payload.source.subagent.thread_spawn.parent_thread_id` is the
subagent signal. Absence means root session.

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

`SessionStart`, `UserPromptSubmit`, and `Stop` accept:

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

## TeleClaude mapping

TeleClaude subscribes this subset of Codex's native hook surface:

- `SessionStart` → internal `session_start`
- `UserPromptSubmit` → internal `user_prompt_submit`
- `PreToolUse` → internal `tool_use`
- `Stop` → internal `agent_stop`

The remaining native events are cataloged in `teleclaude.core.events.AgentHookEvents.HOOK_EVENT_MAP["codex"]`
as `None` — TeleClaude knows the events exist but does not install them:

- `PostToolUse` (cataloged, not ingested)
- `PermissionRequest` (cataloged, not ingested)

Payload normalization done by `teleclaude/hooks/adapters/codex.py`:

- `prompt` stays `prompt`
- `last_assistant_message` → `message`

## TeleClaude notes

- The receiver reads `hook_event_name` from stdin and maps it through the shared
  adapter path; no positional event argument is required for Codex.
- TeleClaude uses native `Stop` continuation JSON for checkpointing.
- TeleClaude emits Codex `SessionStart` additional context via the
  `systemMessage` field on stdout JSON.
- Subagent detection in TeleClaude reads the transcript's `session_meta` line
  via `teleclaude.core.codex_transcript.read_codex_transcript_meta` — required
  because the hook payload does not expose parent linkage.

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

`telec projects init` writes these entries deterministically via
`teleclaude.install.codex_hook_trust`, so a fresh codex session picks up the
hooks without forcing the operator through the `/hooks` TUI. The installer
overwrites `trusted_hash` on every run (it must track the current command) but
preserves any user-set `enabled = false`.

## Sources

- https://developers.openai.com/codex/hooks
- https://github.com/openai/codex/pull/20321
