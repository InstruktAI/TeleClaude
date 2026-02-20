# Requirements: mcp-migration-doc-updates

## Goal

Update all architecture, policy, and spec docs that reference the MCP server
to reflect the new tool system architecture.

## Scope

### In scope

- Rewrite `project/design/architecture/mcp-layer.md` → `tool-system.md`
  (new architecture: tc CLI → JSON-RPC → daemon handlers)
- Update `project/design/architecture/system-overview.md` — replace MCP
  in diagrams with tc/tool-specs
- Update `project/design/architecture/daemon.md` — remove MCP service
- Rewrite `project/policy/mcp-connection-management.md` → delete
  (no longer applicable)
- Rewrite `project/policy/mcp-tool-filtering.md` → `tool-disclosure.md`
  (role-based context-selection filtering)
- Rewrite `project/spec/mcp-tool-surface.md` → `tool-surface.md`
  (references tool spec docs and tc CLI)
- Update AGENTS.master.md to remove any remaining MCP references
- Run `telec sync` to update index

### Out of scope

- Writing new tool spec docs (done in Phase 2)
- Code changes (done in Phase 5)
- Third-party docs

## Success Criteria

- [ ] No doc snippet contains "MCP server" as current architecture
- [ ] `mcp-layer.md` replaced by `tool-system.md`
- [ ] `mcp-tool-filtering.md` replaced by `tool-disclosure.md`
- [ ] `mcp-tool-surface.md` replaced by `tool-surface.md`
- [ ] `mcp-connection-management.md` deleted
- [ ] System overview diagram shows tc/tool-specs instead of MCP
- [ ] `telec sync --validate-only` passes
- [ ] Context index reflects new doc IDs

## Constraints

- Historical MCP docs may be referenced by other docs — update all cross-references
- Doc IDs change when files are renamed — update any hardcoded references

## Risks

- Stale references in CLAUDE.md baseline index — must regenerate after doc changes
