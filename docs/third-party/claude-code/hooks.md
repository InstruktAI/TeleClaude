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

## Background command hooks

Command hooks support `async: true`. It starts the hook process and Claude Code
continues without waiting; the field is unavailable for HTTP, MCP-tool, prompt,
and agent hooks. An asynchronous hook cannot block, approve, rewrite, or
continue the operation that triggered it.

Async output preserves the informational injection channel: after the process
exits, Claude Code delivers `additionalContext` and `systemMessage` from its
JSON response to Claude on the next conversation turn. When idle, that means
the next user interaction; ordinary async completion does not itself start a
turn. The output contract of the event still applies: events without a context
channel cannot become injectable merely by being asynchronous.

`asyncRewake: true` implies `async`. On exit code `2`, it immediately wakes
Claude even while idle and presents stderr (or stdout when stderr is empty) as
a system reminder. This is not an ordinary successful-output delivery path.
`statusMessage` is separate: it only supplies the spinner text while a hook is
running. The reference does not publish an event-by-event async allowlist;
only command-hook eligibility and each event's output contract are explicit.

## Hook events

Full event surface per the upstream hooks reference, verified against the
installed 2.1.237 binary (all names below occur in the executable):

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

## Per-event capability matrix

All rows include the common `session_id`, `transcript_path`, `cwd`, and
`hook_event_name` fields; `permission_mode` is present where the runtime
reports permission state. Context injection means model-visible content, not a
display-only `systemMessage`, an external side effect, or a control decision.

| Event                 | Additional input fields                                                                                                              | Context injection                                                                                                                        | Activity signal for UI cadence                                                        | Lifecycle discriminator / frequency                                                                                                                               |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SessionStart`        | `source`; optional `model`, `agent_type`, `session_title`                                                                            | Yes: plain stdout or `hookSpecificOutput.additionalContext`, before the first prompt.                                                    | Session-start state, not assistant output.                                            | `source` is `startup`, `resume`, `clear`, `compact`, or `fork`; once for each start/resume position.                                                              |
| `SessionEnd`          | `reason`                                                                                                                             | No; output fields are discarded.                                                                                                         | Terminal-session state.                                                               | `reason` is `clear`, `resume`, `logout`, `prompt_input_exit`, or `other`; once on termination.                                                                    |
| `Setup`               | `trigger`                                                                                                                            | Yes: `hookSpecificOutput.additionalContext`.                                                                                             | Explicit setup state, not assistant output.                                           | `trigger` is `init` or `maintenance`; fires only for the corresponding CLI invocation, never an assistant message.                                                |
| `UserPromptSubmit`    | `prompt`                                                                                                                             | Yes: plain stdout or `hookSpecificOutput.additionalContext`, alongside the submitted prompt.                                             | User-input state, not agent output.                                                   | No sequence field; once per submitted prompt.                                                                                                                     |
| `UserPromptExpansion` | `expansion_type`, `command_name`, `command_args`, `command_source`, `prompt`                                                         | Yes: `hookSpecificOutput.additionalContext`, alongside the expanded prompt.                                                              | Typed-command expansion state.                                                        | `expansion_type` and `command_name`; once per expanded command, before model processing.                                                                          |
| `Stop`                | `stop_hook_active`, `last_assistant_message`, `background_tasks`, `session_crons`                                                    | Yes: `hookSpecificOutput.additionalContext` is model feedback; `decision: "block"`/`reason` is the next instruction.                     | Completed assistant output plus stop state.                                           | `stop_hook_active` marks a hook-forced continuation; one per assistant response, but it can recur across continuations (maximum eight blocks).                    |
| `StopFailure`         | `error`, optional `error_details`, optional `last_assistant_message`                                                                 | No; output and exit code are ignored except `terminalSequence`.                                                                          | API-failure state; `last_assistant_message` is rendered error text, not agent output. | `error` identifies the failure type; once for a failed terminal turn instead of `Stop`.                                                                           |
| `PreToolUse`          | `tool_name`, `tool_input`, `tool_use_id`                                                                                             | Yes: `hookSpecificOutput.additionalContext` before tool execution.                                                                       | Tool-attempt state.                                                                   | `tool_use_id` identifies the call; once per tool call and can repeat within one assistant message.                                                                |
| `PermissionRequest`   | `tool_name`, `tool_input`, optional `permission_suggestions`                                                                         | No context field; a deny `hookSpecificOutput.decision.message` is tool feedback to Claude.                                               | Permission-wait state.                                                                | Tool name/input identify the request; only calls about to prompt (or auto-deny without a prompt), and can repeat within one message.                              |
| `PermissionDenied`    | `tool_name`, `tool_input`, `tool_use_id`, `reason`                                                                                   | No context field; `hookSpecificOutput.retry: true` adds a retry message to Claude.                                                       | Auto-mode denial state.                                                               | `tool_use_id` and `reason`; once per auto-mode denial and can repeat within one message.                                                                          |
| `PostToolUse`         | `tool_name`, `tool_input`, `tool_response`, `tool_use_id`, optional `duration_ms`                                                    | Yes: `hookSpecificOutput.additionalContext` alongside the successful result.                                                             | Successful-tool state.                                                                | `tool_use_id`; once per successful tool call and can repeat within one assistant message (parallel calls run concurrently).                                       |
| `PostToolUseFailure`  | `tool_name`, `tool_input`, `tool_use_id`, `error`, optional `is_interrupt`, optional `duration_ms`                                   | Yes: `hookSpecificOutput.additionalContext` alongside the error.                                                                         | Failed-tool state.                                                                    | `tool_use_id`, `error`, and `is_interrupt`; once per started tool that fails and can repeat within one assistant message.                                         |
| `PostToolBatch`       | `tool_calls` (each has `tool_name`, `tool_input`, `tool_use_id`, `tool_response`)                                                    | Yes: `hookSpecificOutput.additionalContext`, once before the next model call.                                                            | Resolved-tool-batch state.                                                            | The batch array distinguishes the position; exactly once after each resolved batch, and multiple batches can occur in one assistant message.                      |
| `MessageDisplay`      | `turn_id`, `message_id`, `index`, `final`, `delta`                                                                                   | No: `hookSpecificOutput.displayContent` replaces only displayed text.                                                                    | **Assistant-text output**.                                                            | `message_id` is stable, `index` is zero-based, and `final` marks the last batch; repeats for streaming batches in one message, once per message in `-p`/SDK mode. |
| `Notification`        | `message`, optional `title`, `notification_type`                                                                                     | No; only `terminalSequence` survives.                                                                                                    | Notification state, not assistant output.                                             | `notification_type` names the cause; no counter. It can recur whenever the corresponding notification condition recurs.                                           |
| `SubagentStart`       | `agent_id`, `agent_type`                                                                                                             | Yes, but only as `hookSpecificOutput.additionalContext` in the new subagent's initial context, not the parent turn.                      | Subagent-start state.                                                                 | `agent_id` and `agent_type`; once per spawned subagent.                                                                                                           |
| `SubagentStop`        | `stop_hook_active`, `agent_id`, `agent_type`, `agent_transcript_path`, `last_assistant_message`, `background_tasks`, `session_crons` | Yes, but only to continue the subagent: `hookSpecificOutput.additionalContext`, or `decision: "block"`/`reason` as its next instruction. | Subagent completion; exposes its final output.                                        | `agent_id` and `stop_hook_active`; one per subagent response, recurring only across hook-forced continuations.                                                    |
| `TaskCreated`         | `task_id`, `task_subject`, optional `task_description`, `teammate_name`, `team_name`                                                 | No context field; a block is returned as the `TaskCreate` tool error.                                                                    | Task-creation state.                                                                  | `task_id`; once per `TaskCreate`, and can repeat within one assistant message.                                                                                    |
| `TaskCompleted`       | `task_id`, `task_subject`, optional `task_description`, `teammate_name`, `team_name`                                                 | No context field; exit code 2 returns feedback as a task error.                                                                          | Task-completion state.                                                                | `task_id`; fires for `TaskUpdate` completion or a teammate ending with in-progress tasks, and can repeat within one message.                                      |
| `ConfigChange`        | `source`, optional `file_path`                                                                                                       | No; it can block application of eligible config changes, but does not inject context.                                                    | Configuration-change state.                                                           | `source` is `user_settings`, `project_settings`, `local_settings`, `policy_settings`, or `skills`; repeats per change.                                            |
| `FileChanged`         | `file_path`, `event`                                                                                                                 | No; `watchPaths` and `systemMessage` do not reach Claude.                                                                                | Filesystem-change state.                                                              | `event` is `change`, `add`, or `unlink`; repeats per watched change, including changes made outside Claude Code.                                                  |
| `CwdChanged`          | `old_cwd`, `new_cwd`                                                                                                                 | No; `systemMessage` is terminal-only.                                                                                                    | Working-directory transition.                                                         | The old/new path pair identifies each transition; repeats on every directory change.                                                                              |
| `DirectoryAdded`      | `directory`, `source`                                                                                                                | No in the running turn; only `systemMessage` from `/add-dir` reaches Claude on the **next** turn (SDK registration logs it only).        | Added-directory state.                                                                | `source` is `slash_command` or `register_repo_root`; once per successful add.                                                                                     |
| `WorktreeCreate`      | `name`                                                                                                                               | No; command stdout is interpreted as the created worktree path.                                                                          | Worktree-creation state.                                                              | `name` identifies the worktree; once per creation request.                                                                                                        |
| `WorktreeRemove`      | `worktree_path`                                                                                                                      | No; output fields are discarded.                                                                                                         | Worktree-removal state.                                                               | `worktree_path`; once per cleanup occurrence.                                                                                                                     |
| `InstructionsLoaded`  | `file_path`, `memory_type`, `load_reason`, optional `globs`, `trigger_file_path`, `parent_file_path`                                 | No; output fields are discarded.                                                                                                         | Instruction-loading state.                                                            | `load_reason` distinguishes eager and lazy loads; can repeat within a message as instruction files load.                                                          |
| `PreCompact`          | `trigger`, `custom_instructions`                                                                                                     | No; it can block compaction but does not inject context.                                                                                 | Pending-compaction state.                                                             | `trigger` is `manual` or `auto`; once for each compaction attempt.                                                                                                |
| `PostCompact`         | `trigger`, `compact_summary`                                                                                                         | No; output fields are discarded.                                                                                                         | Completed-compaction state.                                                           | `trigger` is `manual` or `auto`; once per completed compaction.                                                                                                   |
| `Elicitation`         | `mcp_server_name`, `message`, optional `mode`, `url`, `elicitation_id`, `requested_schema`                                           | No; `hookSpecificOutput.action`/`content` answers the MCP request rather than injecting model context.                                   | MCP user-input-request state.                                                         | MCP server plus optional `elicitation_id` and `mode`; once per elicitation request and can repeat in a tool workflow.                                             |
| `ElicitationResult`   | `mcp_server_name`, `action`, optional `mode`, `elicitation_id`, `content`                                                            | No; `hookSpecificOutput.action`/`content` changes the response sent to the MCP server.                                                   | MCP elicitation-result state.                                                         | MCP server, `action`, and optional `elicitation_id`; once per user response and can repeat in a tool workflow.                                                    |
| `TeammateIdle`        | `teammate_name`, `team_name`                                                                                                         | No context field; exit code 2 gives feedback to the teammate and keeps it working.                                                       | Teammate-about-to-idle state.                                                         | `teammate_name`; once when that teammate finishes a turn, recurring only after further teammate turns.                                                            |

## PostToolBatch

Fires exactly once after every tool call in a batch has resolved, before the
next request is sent to the model — unlike `PostToolUse`, which fires per tool
(concurrently for parallel calls). No matcher support. Upstream documents it as
the intended place to inject context that depends on the set of tools that ran.
Output: `additionalContext` (string, injected once before the next model call);
`decision: "block"` or `continue: false` stops the agentic loop before that
next call.

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

- `source` (`startup`, `resume`, `clear`, `compact`, or `fork`)

UserPromptSubmit fields:

- `prompt` (string)

Stop fields:

- `stop_hook_active` (boolean)
- `last_assistant_message` (optional string)

SessionEnd fields:

- `reason` (`clear`, `resume`, `logout`, `prompt_input_exit`, or `other`)

Notification fields:

- `message` (string)
- `title` (optional string)
- `notification_type`:
  - `permission_prompt`
  - `idle_prompt`
  - `auth_success`
  - `elicitation_dialog`
  - `elicitation_url_dialog`
  - `elicitation_complete`
  - `elicitation_response`
  - `agent_needs_input` (Claude Code 2.1.198+; background session waiting for input)
  - `agent_completed` (Claude Code 2.1.198+; background session finished or failed)

`Notification` is an observability/side-effect hook. It cannot block or modify the
native notification. `PermissionRequest` is the separate pre-prompt decision hook;
`Elicitation` and `ElicitationResult` are the separate MCP interaction hooks.

## Sources

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/hooks-guide
- https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
