# Requirements: deployment-cleanup

## Goal

Remove the manual `telec deploy` command and its backing infrastructure now that
automated deployment via webhook-driven channels handles updates. Update
documentation to reflect the new automated flow.

## Scope

### In scope

1. **Remove MCP tool** — `telec deploy` from tool definitions, handlers,
   and role_tools. **Conditional**: if `mcp-migration-delete-mcp` has already run,
   MCP tools are gone. The grep-first approach handles this naturally.
2. **Remove deploy dispatch paths** — daemon system command handler, MCP server
   dispatch, transport layer deploy arg construction.
3. **Remove deploy service** — `teleclaude/services/deploy_service.py`.
4. **Remove deploy data structures** — `DeployArgs` from `core/events.py`.
5. **Remove deploy lifecycle check** — deploy status block in `core/lifecycle.py`.
6. **Update documentation** — procedure doc, spec docs, architecture overview, README.
7. **Write deployment pipeline doc** — new architecture doc describing the
   automated webhook-driven flow.

### Out of scope

- Modifying the new deployment pipeline code (done in earlier phases)
- Removing `tools/verify_deploy.py` if repurposable for the new system

## Success Criteria

- [ ] `telec deploy` MCP tool no longer exists (or MCP already removed)
- [ ] No deploy dispatch path remains in daemon, MCP server, or transport
- [ ] `deploy_service.py` is deleted
- [ ] `DeployArgs` dataclass is removed from `core/events.py`
- [ ] Deploy status check in `core/lifecycle.py` is removed
- [ ] All docs reference the new automated deployment flow
- [ ] New `docs/project/design/architecture/deployment-pipeline.md` exists
- [ ] `make lint` and `make test` pass

## Constraints

- Must not break existing tests that reference deploy indirectly
- Removal order: consumers before providers (handlers → service → events)
- Must check what still exists before removing (MCP migration may have already
  cleaned up MCP-specific code)

## Dependencies

- `deployment-channels` — the new pipeline must be in place before removing old

## Risks

- **Orphaned references**: deploy_service might be imported in unexpected places.
  Mitigation: grep for all references before removing.
- **Test dependencies**: some tests may mock or reference deploy.
  Mitigation: search test files and update/remove.
- **MCP migration ordering**: if `mcp-migration-delete-mcp` runs first, MCP tool
  removal tasks are already done. Plan must handle both orderings gracefully.
