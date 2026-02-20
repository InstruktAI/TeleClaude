# Requirements: mcp-migration-context-integration

## Goal

Wire the 24 tool spec docs into the context-selection pipeline so that baseline
tools appear automatically in agent system prompts and advanced tools are
discoverable on demand via `telec context query` (formerly `get_context`).

## Scope

### In scope

- Configure baseline tool specs to auto-load in system prompt
- Configure on-demand tool specs for progressive disclosure
- Update AGENTS.master.md to reference new tool system instead of MCP
- Map role-based MCP filtering to context-selection disclosure rules
- Regenerate AGENTS.md / CLAUDE.md
- Validate progressive disclosure works end-to-end

### Out of scope

- Writing the tool spec docs (done in prior phase)
- Building the tc CLI (done in prior phase)
- Removing MCP (later phase)

## Success Criteria

- [ ] 6 baseline tool specs auto-loaded in agent system prompts
- [ ] `telec context query --areas spec` shows tool spec index entries
- [ ] Worker role does not see workflow/ or infrastructure/ tool specs
- [ ] Customer role sees minimal tool set
- [ ] Admin role sees all tool specs
- [ ] AGENTS.md contains tool system guidance (telec usage, discovery)
- [ ] No MCP-specific baseline references remain in AGENTS.md

## Constraints

- Must not break existing get_context behavior during transition
- MCP server still runs in parallel during this phase
- Role filtering must be at least as restrictive as current MCP filtering

## Risks

- Context window pressure: 6 baseline tool specs add tokens to every session.
  Keep baseline specs concise (parameters + invocation only, no extended docs).
