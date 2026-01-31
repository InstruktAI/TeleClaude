---
id: project/policy/mcp-tool-filtering
type: policy
scope: project
description: Role-based filtering of teleclaude tools to enforce least-privilege for scoped agents.
---

# MCP Tool Filtering — Policy

## Rules

- The MCP wrapper filters `teleclaude__*` tools based on the agent's role.
- When the wrapper receives a `teleclaude__run_agent_command(cmd="/next-{step}")` call, it sets the agent role to `worker`.
- Role-based tool access:
  - `worker`: orchestration tools are hidden.
  - No role: all `teleclaude__*` tools are exposed.

## Rationale

Agents dispatched to execute a single atomic command should not have access to orchestration tools. Restricting the tool surface prevents scoped workers from accidentally starting sessions, ending sessions, or interfering with other agents.

## Scope

Applies to all MCP-connected agent sessions managed by the wrapper.

## Enforcement

- The wrapper reads the `teleclaude_role` file to determine active role.
- Tool lists returned to the agent are filtered before delivery.

## Exceptions

- None.
