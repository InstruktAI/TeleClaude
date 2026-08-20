---
description: dsh-hooks — Claude Code contract hooks for DeepSeek Harness
---

# DeepSeek Harness Hooks

## Overview

DeepSeek Harness (`dsh`) has no native hook system. Hooks come from the
`dsh-hooks` plugin, which advertises adherence to the Claude Code hook
contract: the same `hooks.json` configuration shape, the same stdin JSON input,
and the same stdout JSON decision protocol.

A Claude Code hook _script_ — a command reading the stdin payload and writing a
stdout decision — runs against it unchanged. A Claude Code hook _configuration_
carries over only within the supported subset; entries using fields this
executor does not implement are rejected at parse time and require adaptation
(see Compatibility limits).

That adherence is why a Claude-shaped hook client works against this runtime
without a distinct protocol implementation.

## Background execution

The installed `dsh-hooks` plugin has no configured background-hook capability.
Its parser rejects truthy `async`, `asyncRewake`, and `statusMessage` fields
rather than silently accepting them. This is the plugin's present contract,
not evidence about what the underlying DeepSeek Harness could support. The
harness-level async, injection, wake, and per-event semantics remain open.

The executor recognizes an `{"async":true}` first line in a hook's returned
stdout only after the command has already completed. In this v1 implementation
that marker suppresses the synchronous decision and `additionalContext`; it
does not background the command or defer injection. It therefore cannot remove
the invocation cost.

## Events

`PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`,
`UserPromptSubmit`, `SessionStart`, `SessionEnd`, `Stop`, `StopFailure`,
`SubagentStart`, `SubagentEnd`.

The installed plugin and its current README both list all eleven events.
`PostToolBatch` fires once per non-empty tool batch before the next model call
— a turn making no tool calls produces no firing. `PostToolUse` fires per tool
call, and `PostToolUseFailure` is its error branch.

## Context injection by event

Which events honor `hookSpecificOutput.additionalContext` back into the running
turn:

| Event                | Mechanism                                                                                                |
| -------------------- | -------------------------------------------------------------------------------------------------------- |
| `SessionStart`       | injected as a text user message                                                                          |
| `UserPromptSubmit`   | injected as a text user message                                                                          |
| `PreToolUse`         | injected as a text user message; `permissionDecision` and `permissionDecisionReason` affect tool control |
| `PostToolUse`        | native `decision.additionalContexts` channel into the loop's active-batch FIFO                           |
| `PostToolUseFailure` | same channel as `PostToolUse`                                                                            |
| `PostToolBatch`      | appended to the pre-step's claimed messages, injected once before the next model call                    |
| `Stop`               | injected as a user message, keeping the turn going                                                       |

When several hooks fire for one event, all of them execute and every
`additionalContext` is injected; the last matching layer does not win.

## Per-event capability matrix

All rows also receive `session_id`, `transcript_path`, `cwd`,
`permission_mode`, and `hook_event_name`. Context injection means a hook
response that the plugin routes into model-visible input; it excludes a hook
command's ordinary stdout and logging. An activity signal is scoped to the
event's lifecycle position, not a streaming-text signal. An ordinary event
triggered by a child agent also carries `agent_id`, `agent_type`, and
`delegation_depth`; the dedicated subagent lifecycle events instead carry the
child identity while running at the delegator.

| Event                | Additional input fields                                                                                                   | Context injection                                                                                                                                                                                                                                         | Activity signal for UI cadence                                                      | Lifecycle discriminator and frequency                                                                                                                                     |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SessionStart`       | `source` (defaults to `startup`)                                                                                          | Yes: `hookSpecificOutput.additionalContext` is converted to a text user message through `agent.inject()`.                                                                                                                                                 | Session-start state only, not assistant output.                                     | `source` distinguishes the upstream start reason. The source establishes no counter or repeated firing within one assistant message.                                      |
| `SessionEnd`         | `reason: "exit"`                                                                                                          | No. The executor runs hooks but consumes no decision or context.                                                                                                                                                                                          | Terminal agent-state signal only, not assistant output.                             | `reason` is fixed to `exit`. The disposed-agent path cleans up its controller; plugin unload handles only still-live controllers.                                         |
| `SubagentStart`      | `agent_id`, `agent_type` for the child                                                                                    | No. The executor runs hooks but consumes no decision or context.                                                                                                                                                                                          | Delegation-start state signal, not child output.                                    | `agent_id` and `agent_type` identify the child. It fires at the delegator; no counter or idle flag is supplied.                                                           |
| `PreToolUse`         | `tool_name`, `tool_input`, `tool_use_id`                                                                                  | Yes: `hookSpecificOutput.additionalContext` becomes a text user message through `agent.inject()`. `permissionDecision`, `permissionDecisionReason`, and `updatedInput` are parsed but only the permission decision is applied by this installed executor. | Tool-attempt signal; the tool has not yet run.                                      | `tool_use_id` identifies the invocation. It fires for each tool call, so it can repeat within one assistant tool batch.                                                   |
| `PostToolUse`        | `tool_name`, `tool_input`, `tool_use_id`, optional text-only `tool_response`                                              | Yes: `hookSpecificOutput.additionalContext` is added to `decision.additionalContexts`, the loop's active-batch channel.                                                                                                                                   | Completed successful-tool signal; the result can represent changed state.           | `tool_use_id` identifies the invocation. It fires for each successful tool result, so it can repeat within one assistant tool batch.                                      |
| `PostToolUseFailure` | `tool_name`, `tool_input`, `tool_use_id`, optional text-only `tool_response`                                              | Yes: the same `hookSpecificOutput.additionalContext` → `decision.additionalContexts` path as `PostToolUse`.                                                                                                                                               | Completed failed-tool signal.                                                       | `tool_use_id` identifies the invocation. It is the `tools/post-execute` error branch and can repeat for failed calls within one assistant tool batch.                     |
| `PostToolBatch`      | Optional numeric `turn`; `tool_calls` entries with `tool_name`, `tool_input`, optional `tool_response`, and `tool_use_id` | Yes: `hookSpecificOutput.additionalContext` is appended as a text user message to the accepted `agent/pre-step` batch before the next model call.                                                                                                         | Completed tool-batch signal.                                                        | `turn` identifies the pre-step when supplied. Fires once for each non-empty pending tool batch; a turn with no tool calls does not fire.                                  |
| `UserPromptSubmit`   | `prompt`                                                                                                                  | Yes: `hookSpecificOutput.additionalContext` is converted to a text user message through `agent.inject()`.                                                                                                                                                 | User-input signal, not agent output or a state change.                              | The installed plugin fires it only for depth-0 inbox insertion; programmatic subagent inbox delivery is excluded. No counter or idle flag is supplied.                    |
| `Stop`               | `stop_hook_active`; optional `last_assistant_message`                                                                     | Yes: `hookSpecificOutput.additionalContext`, or `decision: "block"` with `reason`, is injected as a text user message to continue the turn.                                                                                                               | Turn-stopping signal; `last_assistant_message` may carry the latest assistant text. | `stop_hook_active` marks a stop already continued by this hook. A continued turn can reach a later stop boundary; no sequence counter is supplied.                        |
| `StopFailure`        | Optional `error: { message }`                                                                                             | No. The executor runs hooks but consumes no decision or context.                                                                                                                                                                                          | Turn-error state signal, not assistant output.                                      | `error.message` identifies the observed failure. The installed source supplies no counter, idle flag, or stronger per-message frequency guarantee.                        |
| `SubagentEnd`        | `agent_id`, `agent_type` for the child; optional `last_assistant_message`                                                 | No. The executor runs hooks but consumes no decision or context.                                                                                                                                                                                          | Delegation-end state signal; `last_assistant_message` may carry child output.       | `agent_id` and `agent_type` identify the child. It fires at the delegator only when the start-time parent mapping remains available; no counter or idle flag is supplied. |

The plugin exposes no generic assistant-output delta, activity counter, or idle
indicator. `PreToolUse`, `PostToolUse`, and `PostToolUseFailure` are the
per-tool signals; `PostToolBatch` is the per-batch signal. The remaining rows
record lifecycle transitions and cannot be promoted to model-output progress.

## Protocol

Input is a single line of JSON on stdin carrying `session_id`,
`transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, and
event-specific fields (`tool_name`, `tool_input`, `tool_use_id`, and
`agent_id` / `agent_type` / `delegation_depth` for subagents).

Output is a JSON decision on stdout under `hookSpecificOutput`, with
`hookEventName`, `permissionDecision`, `permissionDecisionReason`, and
`additionalContext`. The channel is one-directional: a hook writes stdout and
exits, and nothing is returned indicating whether the harness consumed it.

## Compatibility limits

Adherence covers configuration shape and decision protocol, not Claude Code's
plugin surface. Claude Code environment variables (`CLAUDE_PROJECT_DIR`,
`CLAUDE_PLUGIN_ROOT`) are not injected — the project root arrives as the `cwd`
input field — and `${CLAUDE_PLUGIN_ROOT}` substitution, `CLAUDE_PLUGIN_OPTION_*`
and `CLAUDE_ENV_FILE` are not implemented. Configuration fields the executor
does not implement (`async`, `asyncRewake`, `statusMessage`, non-`bash` `shell`)
are rejected at parse time rather than ignored.

Configuration resolves in four layers, later overriding earlier: global
`~/.dsh/hooks.json`, preset, project `.dsh/hooks.json`, project-local
`.dsh/hooks.local.json`.

## Sources

- https://github.com/InstruktAI/dsh-plugins
- https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/core.md
