# Input: deployment-cleanup

## Context

Parent todo: `mature-deployment` (decomposed). Phase 5 of 5.
Depends on: `deployment-auto-update`.

## Brain dump

Remove the old manual deploy system now that automated deployment is in place.

### What to remove

- `teleclaude__deploy` MCP tool (definitions, handlers, role_tools)
- `telec deploy` CLI subcommand
- `teleclaude/services/deploy_service.py`
- Deploy-related Redis system command handling
- `tools/verify_deploy.py` and its test (or repurpose for new system)

### What to update

- `docs/project/procedure/deploy.md` — rewrite for new automated flow
- `docs/project/spec/mcp-tool-surface.md` — remove deploy tool
- `docs/project/spec/teleclaude-config.md` — add deployment channel config
- `docs/project/design/architecture/system-overview.md` — reflect new flow
- README.md — update deploy references
- Write new `docs/project/design/architecture/deployment-pipeline.md`

### Error message

When someone runs `telec deploy`, show a helpful error:
"Unknown command 'deploy'. Deployment is now automatic via channels. See: telec version"
