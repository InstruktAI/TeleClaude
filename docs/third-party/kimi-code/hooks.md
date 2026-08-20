---
description: Kimi Code 0.37.2 hook registration, installed event evidence, permission decisions, and the UserPromptSubmit context exception.
---

# Kimi Code Hooks

## Configuration

Kimi Code registers hook rules in `[[hooks]]` entries in `config.toml`. The
documented fields are `event`, optional regular-expression `matcher`,
`command`, and optional `timeout`; the vendor documents a 1–600 second timeout
range with a 30-second default. Hook commands receive JSON on standard input.

The installed 0.37.2 binary validates hook configuration against these 20
event names: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
`PermissionRequest`, `PermissionResult`, `UserPromptSubmit`,
`UserPromptQueued`, `TurnStarted`, `Stop`, `StopFailure`, `Interrupt`,
`SessionStart`, `SessionEnd`, `SessionHeartbeat`, `SubagentStart`,
`SubagentStop`, `TaskStarted`, `PreCompact`, `PostCompact`, and
`Notification`.

## Background execution

Kimi Code 0.37.2 has no configured async/background hook facility. A
`[[hooks]]` entry accepts only `event`, `matcher`, `command`, and `timeout`;
extra fields make the configuration fail to load. It documents neither an
`asyncRewake` equivalent nor a completion-triggered turn.

Matching hooks may run in parallel, and non-blockable events are described as
fire-and-forget, but neither behavior is a marked asynchronous hook with a
deferred model-injection channel. In particular, the documented observation
events do not let return values affect the main flow. The vendor is silent on
any safe-point delivery of a background hook's output, so no such delivery or
per-event async allowance is established.

## Response boundary

The installed binary contains `hookSpecificOutput.permissionDecision` and
`hookSpecificOutput.permissionDecisionReason`. It contains zero occurrences of
`additionalContext`, so 0.37.2 has no generic response field for context
injection. `UserPromptSubmit` is an event-specific exception: successful hook
stdout or a top-level `message` is added to the current turn as a
`<hook_result>` user message.

The current vendor Hooks guide describes a broader and evolving hook surface.
It is a useful configuration reference, but it does not supersede the installed
binary when the two differ.

## Per-event capability matrix

All rows include `hook_event_name`, `session_id`, `session_title`,
`client_type`, and `cwd`. Context injection means hook-produced content that
reaches the model in the triggering turn; a notification or a UI-facing status
is not injection.

| Event                | Additional input fields                                                                                                                                               | Context injection                                                                                                                                                             | Activity signal for UI cadence                                         | Lifecycle discriminator and frequency                                                                                                                                                  |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PreToolUse`         | `tool_name`, `tool_input`, `tool_call_id`                                                                                                                             | No free-form injection field. A deny through `hookSpecificOutput.permissionDecisionReason` or exit-code-2 stderr becomes the denied tool result visible to the model.         | Tool-attempt state signal; not assistant text.                         | `tool_call_id` identifies the call. Fires once for each eligible tool call and can repeat within one assistant message.                                                                |
| `PostToolUse`        | `tool_name`, `tool_input`, `tool_call_id`, `tool_output` (truncated to 2,000 characters)                                                                              | No; fire-and-forget output is ignored.                                                                                                                                        | Successful tool-completion state signal.                               | `tool_call_id` identifies the call. Fires once for each successful eligible tool call and can repeat within one assistant message.                                                     |
| `PostToolUseFailure` | `tool_name`, `tool_input`, `tool_call_id`, `error`                                                                                                                    | No; fire-and-forget output is ignored.                                                                                                                                        | Failed or denied tool-completion state signal.                         | `tool_call_id` identifies the call. Fires once for each failed or denied eligible tool call and can repeat within one assistant message.                                               |
| `PermissionRequest`  | `id`, `agent_id`, `turn_id`, `tool_call_id`, `tool_name`, `action`, `display`, `tool_input`                                                                           | No; observation-only output is ignored.                                                                                                                                       | Approval-wait state signal.                                            | `id` and `tool_call_id` identify the request. Fires for each approval request and can repeat within one assistant message.                                                             |
| `PermissionResult`   | `id`, `agent_id`, `turn_id`, `tool_call_id`, `tool_name`, `action`, `display`, `tool_input`, `decision`; optionally `scope`, `feedback`, `selected_label`, or `error` | No; observation-only output is ignored.                                                                                                                                       | Approval-resolution state signal.                                      | `id` and `tool_call_id` pair it with a request. Fires for each resolved approval and can repeat within one assistant message.                                                          |
| `UserPromptSubmit`   | `prompt`, `is_steer`                                                                                                                                                  | Yes: successful stdout, or top-level `message`, is appended as a `<hook_result>` user message before the model processes the prompt. A block prevents that turn's model call. | User-input boundary, not agent output or an agent-state transition.    | The payload provides no counter or idle flag. Fires once for each submitted user prompt; it does not recur within that prompt's assistant message.                                     |
| `UserPromptQueued`   | `prompt_id`, `prompt`, `queue_length`                                                                                                                                 | No; fire-and-forget output is ignored.                                                                                                                                        | Queued-user-input state signal, not agent output.                      | `prompt_id` identifies the queued prompt; `queue_length` positions it in the queue. Fires for every prompt queued while another turn runs and can repeat within that turn.             |
| `TurnStarted`        | `turn_id`, `origin_kind`, optional `origin_name`, `prompt`                                                                                                            | No; fire-and-forget output is ignored.                                                                                                                                        | Turn-start state signal.                                               | `turn_id` identifies the turn; `origin_kind` is the matcher value. Fires once for each started turn; no per-message repeat counter is exposed.                                         |
| `Stop`               | `stop_hook_active`                                                                                                                                                    | Only on block: exit-code-2 stderr or `permissionDecisionReason` is appended as a continuation user message. There is no free-form injection channel.                          | Main-agent end-of-turn state signal.                                   | `stop_hook_active` records whether this hook has already caused continuation. The runtime invokes it at most once before a continuation it caused; no sequence counter is exposed.     |
| `StopFailure`        | `error_type`, `error_message`                                                                                                                                         | No; fire-and-forget output is ignored.                                                                                                                                        | Failed-turn state signal.                                              | `error_type` distinguishes the failure. Fires once for the failed turn; no counter or idle flag is exposed.                                                                            |
| `Interrupt`          | `turn_id`, `reason`                                                                                                                                                   | No; fire-and-forget output is ignored.                                                                                                                                        | User-interrupt state signal.                                           | `turn_id` and `reason` distinguish the cancelled turn. It fires for a user cancellation, not an arbitrary abort; no repeat count is exposed.                                           |
| `SessionStart`       | `source`, `model`, `profile`                                                                                                                                          | No; observation-only output is ignored.                                                                                                                                       | Session-start state signal.                                            | `source` is the matcher value. The installed runtime does not establish an exhaustive source-value set or a per-message cadence.                                                       |
| `SessionEnd`         | `reason`                                                                                                                                                              | No; observation-only output is ignored.                                                                                                                                       | Session-terminal state signal.                                         | `reason` is the matcher value. The installed runtime does not establish an exhaustive reason-value set or a per-message cadence.                                                       |
| `SessionHeartbeat`   | `uptime_ms`                                                                                                                                                           | No; fire-and-forget output is ignored.                                                                                                                                        | Session-liveness state signal.                                         | No payload counter or idle flag. When configured, it fires every 60 seconds while the session is alive; the runtime starts no heartbeat timer otherwise.                               |
| `SubagentStart`      | `agent_name`, `prompt`                                                                                                                                                | No; observation-only output is ignored.                                                                                                                                       | Subagent-start state signal.                                           | `agent_name` identifies the child profile. Fires for each started subagent and can repeat within one parent assistant message.                                                         |
| `SubagentStop`       | `agent_name`, `response`                                                                                                                                              | No; fire-and-forget output is ignored.                                                                                                                                        | Subagent-completion state signal; `response` carries the child result. | `agent_name` identifies the child profile. Fires for each stopped subagent and can repeat within one parent assistant message.                                                         |
| `TaskStarted`        | `task_id`, `kind`, `description`, `status`, `detached`, `started_at`                                                                                                  | No; fire-and-forget output is ignored.                                                                                                                                        | Background-task-start state signal.                                    | `task_id` identifies the task; `kind` is the matcher value. Fires for each background task that starts and can repeat within one assistant message.                                    |
| `PreCompact`         | `trigger`, `token_count`                                                                                                                                              | No; its return values are ignored.                                                                                                                                            | Pending-compaction state signal.                                       | `trigger` is the matcher value. No counter, idle flag, or evidence of repeat frequency within one assistant message is exposed.                                                        |
| `PostCompact`        | `trigger`, `estimated_token_count`                                                                                                                                    | No; fire-and-forget output is ignored.                                                                                                                                        | Completed-compaction state signal.                                     | `trigger` is the matcher value. No counter, idle flag, or evidence of repeat frequency within one assistant message is exposed.                                                        |
| `Notification`       | `sink` (`context`), `notification_type`, `title`, `body`, `severity`, `source_kind`, `source_id`                                                                      | No; fire-and-forget output is ignored.                                                                                                                                        | Background-task notification state signal.                             | `notification_type` is the matcher value; `source_id` identifies its source. It can fire for each background-task status notification, including while an assistant message is active. |

## Gaps

- No live hook run verified stdin payload fields, matcher behavior, timeout
  handling, or stdout/exit-code handling.
- The installed binary exposes additional hook-related strings, but this record
  only names the event set verified for the current runtime contract.

## Sources

- https://moonshotai.github.io/kimi-code/en/customization/hooks
