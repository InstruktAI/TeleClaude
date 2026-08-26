---
description: Discover and use tools published by third-party MCP servers that do not
  yet have a specialized procedure.
---

# MCP Server Tool Usage — Procedure

## Goal

Discover and use configured MCP servers through TeleClaude's lazy MCP runtime. This procedure is for servers that do not have a specialized procedure; specialized procedures use the same `telec mcp` invocation surface.

## Preconditions

- No specialized procedure exists for the server or task. (If MCP server in the list below instructs to read the specialized procedure, follow that instead.)

## Steps

1. Choose from the available generic MCP servers:

<!-- planned-change:per-project-mcp-registry -->

<!-- @exec: telec mcp list -->

<!-- change:per-project-mcp-registry -->

<!-- @exec: telec mcp list --index -->

<!-- /planned-change:per-project-mcp-registry -->

1. List the selected server's tools with `telec mcp list-tools <slug>`. This initializes or reuses the daemon-owned lease for that one server and prints the tool catalog.

2. Invoke the selected tool with `telec mcp call <slug> <tool> --json '<arguments>'`.

3. Use the returned tool result as evidence for the task, preserving the server name, tool name, and arguments in any report that needs provenance.

## Outputs

- `telec mcp list` returns a secret-safe catalog of configured servers with activation triggers.
- `telec mcp list-tools <slug>` returns the selected server's tool catalog.
- `telec mcp call <slug> <tool> --json '<arguments>'` returns the MCP tool result as JSON.

## Recovery

- If the server is absent from `telec mcp list`, inspect the effective TeleClaude MCP registry inputs (`teleclaude-mcp.jsonc` and `teleclaude-mcp.local.jsonc`) and rerun the list command.
- If `telec mcp list-tools <slug>` reports a missing environment variable, set it through TeleClaude environment configuration and retry.
- If initialization, handshake, or tool-call routing fails after configuration is correct, report a bug with the server slug, tool name, and secret-free error text.

## See Also

- ~/.teleclaude/docs/general/procedure/declare-mcp-server.md — declaring a new MCP server, machine-wide or project-local.
