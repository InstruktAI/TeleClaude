---
description: Antigravity CLI (agy) Sub-Agents Spec
id: third-party/antigravity-cli/sub-agents
scope: project
type: third-party
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

## Sources

- https://antigravity.google/docs/sub-agents
- https://dev.to/google/antigravity-cli-2-0
