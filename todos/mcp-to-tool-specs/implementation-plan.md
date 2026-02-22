# Implementation Plan: mcp-to-tool-specs

## Overview

Phased migration from MCP server to `telec` CLI subcommands. Each phase is
independently shippable. The MCP server runs in parallel until Phase 3 removes it.

The approach: **build the new CLI alongside the old MCP, validate, then cut over.**

The CLI `--help` output IS the documentation. No separate tool spec docs.
`<!-- @exec: telec <cmd> -h -->` in the telec-cli spec doc auto-inlines
rich help text at `telec sync` time.

---

## Phase 1: CLI Subcommands + Rich Help (mcp-migration-telec-commands)

Add `telec` subcommands for all 24 tools. Each subcommand calls the daemon
REST API. Extend the API with 14 new endpoints. Write rich `--help` with
behavioral guidance and examples. Update the telec-cli spec doc with `@exec`
directives for baseline tools.

See `todos/mcp-migration-telec-commands/` for full implementation plan.

---

## Phase 2: Agent Session Cutover (mcp-migration-agent-config)

Remove MCP from agent session bootstrap. Validate all agent types and
workflows work using `telec` subcommands instead of MCP tools.

See `todos/mcp-migration-agent-config/` for requirements.

---

## Phase 3: MCP Deletion + Doc Cleanup (mcp-migration-delete-mcp)

Delete all MCP server code (~3,400 lines). Update architecture and policy
docs that reference MCP. Single atomic commit for clean revert if needed.

See `todos/mcp-migration-delete-mcp/` for requirements.

---

## Phasing and Dependencies

```
Phase 1 (CLI + Help + @exec) ──→ Phase 2 (Agent Cutover) ──→ Phase 3 (Delete MCP + Docs)
```

Linear chain. Phase 1 is the heavy lift. Phase 2 is the validation gate.
Phase 3 is the point of no return.
