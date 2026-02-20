# Requirements: mcp-migration-delete-mcp

## Goal

Delete all MCP server code, wrapper, handlers, tool definitions, and related
infrastructure. This is the point of no return — only executed after Phase 4
validates everything works without MCP.

## Scope

### In scope

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

### Out of scope

- Documentation updates (separate follow-on todo)
- Any behavioral changes — this is pure deletion

## Success Criteria

- [ ] No files matching `*mcp*` remain in `teleclaude/` (excluding .venv)
- [ ] No `bin/mcp-wrapper.py` exists
- [ ] No MCP imports in any Python file
- [ ] `mcp` not in pyproject.toml dependencies
- [ ] Daemon starts cleanly without MCP service
- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] No reference to `teleclaude.sock` (MCP socket) in active code

## Constraints

- Phase 4 must be complete and validated before this phase begins
- Deletion must be a single atomic commit for clean revert if needed

## Risks

- Hidden MCP dependencies: grep thoroughly before deleting
- Test fixtures that reference MCP: must be updated or removed
