# Requirements: deployment-cleanup

## Goal

Remove the manual `telec deploy` command and its backing infrastructure now that
automated deployment via channels handles updates. Update documentation to
reflect the new automated flow.

## Scope

### In scope

1. **Remove MCP tool** — `teleclaude__deploy` from tool definitions, handlers,
   and role_tools.
2. **Remove deploy dispatch paths** — daemon system command handler, MCP server
   dispatch, transport layer deploy arg construction.
3. **Remove deploy service** — `teleclaude/services/deploy_service.py`.
4. **Remove Redis system command handling** for deploy.
5. **Update documentation** — procedure doc, spec docs, architecture overview,
   README.
6. **Write deployment pipeline doc** — new architecture doc describing the
   automated flow.

### Out of scope

- Modifying the new deployment pipeline code (that's done in earlier phases)
- Removing `tools/verify_deploy.py` if it's still useful for the new system

## Success Criteria

- [ ] `teleclaude__deploy` MCP tool no longer exists in tool definitions or handlers
- [ ] No deploy dispatch path remains in daemon, MCP server, or transport layers
- [ ] `deploy_service.py` is deleted
- [ ] `DeployArgs` dataclass is removed from `core/events.py`
- [ ] Deploy status check in `core/lifecycle.py` is removed
- [ ] All docs reference the new automated deployment flow
- [ ] New `docs/project/design/architecture/deployment-pipeline.md` exists
- [ ] `make lint` and `make test` pass with removals

## Constraints

- Must not break any existing tests that reference deploy indirectly
- Removal order matters: consumers before providers (handlers → service → events)

## Risks

- **Orphaned references**: deploy_service might be imported or referenced in
  unexpected places. Mitigation: grep for all references before removing.
- **Test dependencies**: some tests might mock or reference deploy. Mitigation:
  search test files for deploy references and update/remove.
