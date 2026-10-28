---
description: Antigravity CLI (agy) Sub-Agents Spec
---

# Antigravity CLI (agy) Sub-Agents Spec

## Overview

Unlike legacy versions, the Go-based **Antigravity CLI (`agy`)** introduces native support for **Asynchronous Background Sub-Agents**. The parent agent can delegate long-running or specialized sub-tasks (such as code analysis, database debugging, or web research) to dedicated background worker processes.

## Sub-Agent Invocation & Orchestration

Sub-agents are declared and launched dynamically during the session using dedicated tool calls:

- **`define_subagent`**: Registers a new sub-agent role, specifying its name, system prompt, enabled tools (such as write/shell tools), and custom system parameters.
- **`invoke_subagent`**: Spawns one or more active instances of a defined sub-agent with a clear, actionable background prompt task.

### Workspace Isolation

When a sub-agent is invoked, its workspace mode can be configured to manage isolation and storage footprint:

- **`inherit`** (Default): The sub-agent shares the parent's immediate workspace directory.
- **`share`**: Spawns the sub-agent in a git worktree or shared repository directory, enabling parallel branches without duplicate file storage.
- **`branch`**: Clones and isolates the sub-agent's files inside a separate sandbox container.

## Communication & Event Lifecycle

Sub-agents communicate with each other and the parent asynchronously, preventing thread blocking:

1. **Message Passing**: The parent interacts with active sub-agents using the `send_message` tool, passing messages keyed by a unique `ConversationID`.
2. **Reactive Wakeups**: The system automatically schedules background turns. The parent agent does **not** need to poll in a loop; the CLI automatically signals a reactive wakeup when a sub-agent responds or finishes its task.
3. **Lifecycle Controls**: Parent agents can query active workers or terminate branches via the `manage_subagents` tool (supporting actions like `list`, `kill`, and `kill_all`).

## Local Sub-Agent Records (observed, CLI 1.2.13)

The public hook schema carries no parent, ancestry, or sub-agent field: a sub-agent's
hooks present only its own `conversationId` and `transcriptPath`, exactly like a
primary conversation's. Ancestry is recorded only in the CLI's local conversation
store, whose layout is undocumented. The following was observed on CLI 1.2.13 on a
single host and is not a published vendor guarantee.

- Every conversation, primary or sub-agent, has its own directory
  `~/.gemini/antigravity-cli/brain/<conversationId>/`. Its transcript lives under
  `.system_generated/logs/`. In both retained cases examined, one primary and one
  sub-agent, the directory existed before that conversation's first hook.
- The parent records each spawned sub-agent at
  `.system_generated/subagents/<childConversationId>.json`, carrying the child
  `conversationId`, a `subagentDescriptor`, a lifecycle `state`, and the parent's
  `spawnStepIndex`.
- The sub-agent's task arrives as a message record in its own
  `.system_generated/messages/<messageId>.json`. The record's `sender` is the parent
  `conversationId`. Its `sourceMetadata.tool` carries the parent `conversationId`, the
  parent `stepIndex`, and a `toolCall` whose `name` is `invoke_subagent`. In the
  retained case, this record was written before the sub-agent's first hook fired.
- Later records in the same directory come from the sub-agent's own background tasks
  (`sender` of the form `<conversationId>/task-<n>`). They carry no `invoke_subagent`
  source.
- Of 352 local conversations:
  - all 9 parent-indexed sub-agents carried the `invoke_subagent` message record;
  - no other conversation carried one;
  - 232 had no `messages` directory at all, the normal state for a primary
    conversation that never received a message.
- **Gaps:** the layout is unversioned and may change on upgrade. A sub-agent spawned
  by another mechanism, if any exists, was not observed. Record timing is established
  for one sub-agent, not guaranteed.

## Hook timing and idle reporting (observed, CLI 1.4.7)

Observed on 2026-10-28 on one host, from one print-mode run and one interactive
run, each spawning one `research` sub-agent through `invoke_subagent`. Hooks
were recorded by a workspace-scoped probe hook; this is not a vendor guarantee.

- The local store layout above is unchanged: the parent's
  `.system_generated/subagents/<childConversationId>.json` (with `conversationId`,
  `subagentDescriptor`, `state`, `spawnStepIndex`, `workspaceUris`) and the
  child's `invoke_subagent` message record, whose `sourceMetadata.tool.conversationId`
  is the parent's. All 16 parent-indexed sub-agents on the host carried that
  record and no other conversation did.
- The child's `invoke_subagent` record existed at every one of the child's hooks
  and at none of the parent's. It preceded the child's first hook by about 6.1 s
  in print mode and 0.29 s in interactive mode.
- Parent and child hooks carry the same top-level keys and are all spawned by
  the same `agy` process, so neither the payload nor the hook-process ancestry
  tells them apart.
- `fullyIdle` reflects the whole process. In both runs the parent's last `Stop`
  arrived while the sub-agent still ran and reported `fullyIdle: false`; the
  parent did not stop again when the sub-agent finished. The only
  `fullyIdle: true` `Stop` of the turn came from the sub-agent.
- A sub-agent's later message to its parent (`send_message`) wakes the parent:
  its next `PreInvocation` follows immediately.

## Sources

- https://antigravity.google/docs/sub-agents
- https://dev.to/google/antigravity-cli-2-0
