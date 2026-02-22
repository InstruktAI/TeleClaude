# Requirements: mcp-migration-delete-mcp

## Goal

Delete all MCP server code, wrapper, handlers, tool definitions, and related
infrastructure. Update architecture and policy docs that reference MCP.
This is the point of no return — only executed after mcp-migration-agent-config
validates everything works without MCP.

## Scope

### In scope

**Code deletion:**

- Delete `teleclaude/mcp_server.py` (851 lines)
- Delete `teleclaude/mcp/` directory (handlers.py, tool_definitions.py,
  role_tools.py, protocol.py, types.py, **init**.py — ~2,650 lines)
- Delete `bin/mcp-wrapper.py`
- Delete `teleclaude/entrypoints/mcp_wrapper.py`
- Remove MCP server initialization from daemon startup
- Remove MCP socket path creation and constants
- Remove `mcp` package from pyproject.toml dependencies
- Remove `.state.json` MCP tools tracking
- Remove `logs/mcp-tools-cache.json` references
- Clean up MCP-related constants in `teleclaude/constants.py`
- Run `uv lock` to update lockfile

**Documentation cleanup (absorbed from former mcp-migration-doc-updates):**

- Rewrite `project/design/architecture/mcp-layer.md` → `tool-system.md`
  (or delete if architecture doc covers it)
- Update `project/design/architecture/system-overview.md` — remove MCP
  from diagrams, reference telec CLI instead
- Update `project/design/architecture/daemon.md` — remove MCP service
- Delete `project/policy/mcp-connection-management.md` (no longer applicable)
- Rewrite `project/policy/mcp-tool-filtering.md` → role-based tool
  disclosure policy (or delete if telec-cli spec doc covers it)
- Update `project/spec/mcp-tool-surface.md` → reference telec CLI surface
- Remove MCP-specific guidance from AGENTS.master.md
- Regenerate AGENTS.md via `telec sync`

### Out of scope

- Any behavioral changes — this is deletion and doc cleanup
- Telec CLI changes (done in Phase 1)
- Agent session config changes (done in Phase 2)

## Success Criteria

- [ ] No files matching `*mcp*` remain in `teleclaude/` (excluding .venv)
- [ ] No `bin/mcp-wrapper.py` exists
- [ ] No MCP imports in any Python file
- [ ] `mcp` not in pyproject.toml dependencies
- [ ] Daemon starts cleanly without MCP service
- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] No reference to `teleclaude.sock` (MCP socket) in active code
- [ ] No "MCP server" references in architecture docs
- [ ] Policy docs updated to reference telec CLI instead of MCP
- [ ] AGENTS.md regenerated without MCP references

## Constraints

- mcp-migration-agent-config must be complete and validated before this phase begins
- Deletion should be a single atomic commit for clean revert if needed
- Doc cleanup can be a separate commit if needed for clarity

## Risks

- Hidden MCP dependencies: grep thoroughly before deleting
- Test fixtures that reference MCP: must be updated or removed
- Doc snippets referencing MCP in descriptions or index entries
