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
`SubagentEnd`.

The README's feature list omits `PostToolBatch` and `StopFailure`; both are
implemented. `PostToolBatch` fires once per non-empty tool batch before the next
model call — a turn making no tool calls produces no firing, as in Claude Code.
`PostToolUse` fires per tool call, and `PostToolUseFailure` is its error branch.

## Context injection by event

Which events honor `hookSpecificOutput.additionalContext` back into the running
turn:

| Event                | Mechanism                                                                                                   |
| -------------------- | ----------------------------------------------------------------------------------------------------------- |
| `SessionStart`       | injected as a text user message                                                                             |
| `UserPromptSubmit`   | injected as a text user message                                                                             |
| `PreToolUse`         | injected as a text user message; also `permissionDecision`, `permissionDecisionReason`, `updatedInput`      |
| `PostToolUse`        | native `decision.additionalContexts` channel into the loop's active-batch FIFO; also `updatedMCPToolOutput` |
| `PostToolUseFailure` | same channel as `PostToolUse`                                                                               |
| `PostToolBatch`      | appended to the pre-step's claimed messages, injected once before the next model call                       |
| `Stop`               | injected as a user message, keeping the turn going                                                          |

When several hooks fire for one event, all of them execute and every
`additionalContext` is injected; the last matching layer does not win.

## Protocol

Input is a single line of JSON on stdin carrying `session_id`, `cwd`,
`hook_event_name`, and event-specific fields (`tool_name`, `tool_input`,
`tool_use_id`, and `agent_id` / `agent_type` / `delegation_depth` for
subagents).

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
