---
description: Claude Code Hooks
---

# Claude Code Hooks

## Overview

Claude Code hooks run shell commands at lifecycle events. Hooks are configured in settings
files and receive JSON input describing the event.

## Configuration locations

- `~/.claude/settings.json`
- `.claude/settings.json`
- `.claude/settings.local.json`

Managed settings can be enforced by policy files.

## Hook events

Full event surface per the upstream hooks reference, verified against the
installed 2.1.234 binary (all names below occur in the executable):

- Session lifecycle: `SessionStart`, `SessionEnd`, `Setup`
- Turn level: `UserPromptSubmit`, `UserPromptExpansion`, `Stop`, `StopFailure`
- Per tool call: `PreToolUse`, `PermissionRequest`, `PermissionDenied`,
  `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`
- Output/notification: `MessageDisplay`, `Notification`
- Subagent/task: `SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`
- Configuration/files: `ConfigChange`, `FileChanged`, `CwdChanged`,
  `DirectoryAdded`, `WorktreeCreate`, `WorktreeRemove`, `InstructionsLoaded`
- Context: `PreCompact`, `PostCompact`
- MCP: `Elicitation`, `ElicitationResult`
- Team: `TeammateIdle`

## Context-injection capability by event

Which events honor stdout content back into the running turn:

| Event              | Injectable response                                                        |
| ------------------ | -------------------------------------------------------------------------- |
| `SessionStart`     | plain stdout / `additionalContext` becomes session context                 |
| `UserPromptSubmit` | `hookSpecificOutput.additionalContext`; `decision: "block"` rejects prompt |
| `PostToolBatch`    | `additionalContext` — injected once before the next model call             |
| `Stop`             | `decision: "block"` + `reason` continues the turn with reason as prompt    |
| `PreToolUse`       | permission decisions only (`permissionDecision`); no content channel       |
| `PostToolUse`      | `decision: "block"` feedback; `additionalContext` not documented           |
| `MessageDisplay`   | `displayContent` only — display-side; the model never sees it              |

## PostToolBatch

Fires exactly once after every tool call in a batch has resolved, before the
next request is sent to the model — unlike `PostToolUse`, which fires per tool
(concurrently for parallel calls). No matcher support. Upstream documents it as
the intended place to inject context that depends on the set of tools that ran.
Output: `additionalContext` (string, injected once before the next model call);
no `decision` control.

Absent from the upstream changelog; presence and behavior verified empirically
on 2.1.234 (2026-08-17): the hook fired once for a one-tool batch and its
`additionalContext` reached the model, which quoted it verbatim. Captured input
payload:

- `session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`
- `prompt_id` (string; observed instead of a `turn_id` field)
- `tool_calls`: array of `{tool_name, tool_input, tool_response, tool_use_id}`

Caveat: a turn that makes no tool calls produces no `PostToolBatch` firings.

## MessageDisplay

Added in 2.1.149. Fires while assistant message text is displayed — per batch
of newly completed lines in interactive runs (several calls for a long
message), once per completed message in `claude -p` / Agent SDK runs. Fires for
assistant text only; tool-call-only responses do not trigger it. Synchronous
(each batch is held until the hook returns); default timeout 10 seconds; no
matcher support.

Input: `turn_id`, `message_id` (stable across batches of one message), `index`
(zero-based batch index), `final` (true on the last batch), `delta` (newly
completed lines), plus common fields.

Output: `displayContent` only, which replaces the delta **on screen**.
`MessageDisplay` has no decision control: it cannot block the message or change
what is stored in the transcript or sent to the model — `systemMessage` and
`continue` are discarded. It is display-side observability only and is not a
context-injection channel.

## StopFailure

Fires when the turn ends due to an API error (rate limit, auth failure, etc.).

## Hook input contract (selected fields we use)

Base fields (all events):

- `session_id` (string)
- `transcript_path` (string)
- `permission_mode` (string: `default`, `plan`, `acceptEdits`, `bypassPermissions`)
- `hook_event_name` (string)

SessionStart fields:

- `source` (`startup`)

UserPromptSubmit fields:

- `prompt` (string)

Stop fields:

- `stop_hook_active` (boolean)
- `last_assistant_message` (optional string)

SessionEnd fields:

- `reason` (`exit`)

Notification fields:

- `message` (string)
- `title` (optional string)
- `notification_type`:
  - `permission_prompt`
  - `idle_prompt`
  - `auth_success`
  - `elicitation_dialog`
  - `elicitation_complete`
  - `elicitation_response`
  - `agent_needs_input` (Claude Code 2.1.198+; background session waiting for input)
  - `agent_completed` (Claude Code 2.1.198+; background session finished or failed)

`Notification` is an observability/side-effect hook. It cannot block or modify the
native notification. `PermissionRequest` is the separate pre-prompt decision hook;
`Elicitation` and `ElicitationResult` are the separate MCP interaction hooks.

## TeleClaude adapter mapping

Mapping rules:

- `SessionStart` → `event_type = "session_start"`
  - Requires `data.session_id` (native session id).
  - Requires `data.transcript_path` (native transcript path).
- `UserPromptSubmit` → `event_type = "prompt"`
  - Extracts `data.prompt` to update `last_message_sent` in the database.
- `PreToolUse` → `event_type = "tool_use"` (drives TUI activity)
- `Stop` → `event_type = "stop"`
- Other catalogued Claude signatures (`PostToolUse`, `PostToolUseFailure`,
  `SubagentStart`, `SubagentStop`, `SessionEnd`, `PreCompact`) map to `None`.
- The remaining events (`PostToolBatch`, `MessageDisplay`, `StopFailure`,
  `Notification`, `PermissionRequest`, `PostCompact`, `Setup`,
  `UserPromptExpansion`, `PermissionDenied`, `TaskCreated`, `TaskCompleted`,
  the configuration/file events, `Elicitation`, `ElicitationResult`, and
  `TeammateIdle`) are not catalogued or installed by TeleClaude. Native
  human-attention notifications therefore never enter the current TeleClaude
  notification pipeline.

## Human-attention integration boundary

Claude's native `Notification` event is the authoritative ingress for user-attention
states. TeleClaude should consume the structured notification type and session ID;
it must not infer the same intent from transcript text or tool names. In particular,
`agent_needs_input`, `permission_prompt`, `idle_prompt`, and `elicitation_dialog`
are distinct upstream reasons even when they eventually share a human notification
renderer.

## Sources

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/hooks-guide
- https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
