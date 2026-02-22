# Requirements: mcp-migration-context-integration

## Goal

Update AGENTS.master.md to reference the new tool spec docs and telec
subcommands instead of MCP. Regenerate AGENTS.md/CLAUDE.md. Verify
progressive disclosure works end-to-end for all tool spec groups.

The progressive disclosure mechanism already exists — tool specs are doc
snippets with frontmatter, `telec sync` indexes them, `get_context` serves
them on demand, and `baseline: true` controls auto-loading. This todo wires
the new tool specs into that existing system.

## Scope

### In scope

- Update AGENTS.master.md baseline index to reference tool spec docs
- Add baseline tool specs (6 tools) to the auto-loaded section
- Add on-demand tool group index with descriptions
- Add role metadata to tool spec frontmatter for filtering
- Map MCP role filtering to context-selection disclosure:
  - Worker → exclude workflow/ and infrastructure/
  - Customer → minimal tool set
  - Admin → all tools
- Remove MCP-specific baseline references from AGENTS.master.md
- Regenerate AGENTS.md / CLAUDE.md via `telec sync`
- Verify `telec docs --areas spec` shows tool spec index entries
- Verify role-based filtering works

### Out of scope

- Writing tool spec docs (done in Phase 2)
- Building telec subcommands (done in Phase 1)
- Removing MCP server (later phase)
- Changes to the context-selection engine itself (already works)

## Success Criteria

- [ ] 6 baseline tool specs auto-loaded in agent system prompts
- [ ] `telec docs --areas spec` shows tool spec index entries
- [ ] Worker role does not see workflow/ or infrastructure/ tool specs
- [ ] Customer role sees minimal tool set
- [ ] AGENTS.md contains tool system guidance (telec usage, discovery)
- [ ] No MCP-specific baseline references remain in AGENTS.md
- [ ] `telec sync --validate-only` passes

## Constraints

- Must not break existing get_context behavior during transition
- MCP server still runs in parallel during this phase
- Role filtering must be at least as restrictive as current MCP filtering

## Risks

- Context window pressure: 6 baseline tool specs add tokens to every session.
  Keep baseline specs concise (parameters + invocation only, no extended docs).
