# Input: deployment-cleanup

## Context

Parent todo: `mature-deployment` (decomposed). Phase 4 of 4 (final).
Depends on: `deployment-channels`.

## Brain dump

Remove the old manual deploy system now that automated deployment is in place.

### What to remove

- `telec deploy` MCP tool (definitions, handlers, role_tools) — IF MCP
  tools still exist. The `mcp-migration-delete-mcp` roadmap item may have already
  removed all MCP code. Check before attempting removal.
- `teleclaude/services/deploy_service.py`
- Deploy-related Redis system command handling in daemon
- `DeployArgs` in `core/events.py`
- Deploy dispatch paths in transport layer
- `tools/verify_deploy.py` and its test (or repurpose)

### What to update

- `docs/project/procedure/deploy.md` — rewrite for automated flow
- `docs/project/spec/teleclaude-config.md` — add deployment channel config
- `docs/project/design/architecture/system-overview.md` — reflect new flow
- README.md — update deploy references
- Write new `docs/project/design/architecture/deployment-pipeline.md`

### MCP migration ordering note

If `mcp-migration-delete-mcp` runs before this todo, the MCP tool removal tasks
are already done. The cleanup plan must check what exists before removing.
Grep-first approach handles this naturally.
