# Demo: deployment-cleanup

## Validation

```bash
# MCP deploy tool is gone
! grep -q "telec deploy" teleclaude/mcp/tool_definitions.py
echo "OK: deploy tool removed from definitions"
```

```bash
# Deploy service is gone
[ ! -f teleclaude/services/deploy_service.py ]
echo "OK: deploy_service.py deleted"
```

```bash
# New deployment pipeline doc exists
[ -f docs/project/design/architecture/deployment-pipeline.md ]
echo "OK: deployment pipeline doc exists"
```

```bash
# No orphaned deploy references in code (excluding docs about the new system)
count=$(grep -r "deploy_service\|DeployService" teleclaude/ --include="*.py" | wc -l)
[ "$count" -eq 0 ]
echo "OK: no orphaned deploy_service references"
```

## Guided Presentation

### Step 1: Removed surfaces

Show that `telec deploy` is gone from MCP tool definitions, handlers, and
role_tools. Show that `deploy_service.py` no longer exists.

### Step 2: Helpful error message

Run `telec deploy` (or attempt to). Observe: helpful message "Deployment is now
automatic via channels. See: telec version" instead of a cryptic error.

### Step 3: Updated documentation

Show the new `docs/project/design/architecture/deployment-pipeline.md` that
describes the automated flow. Show updated procedure doc and config spec.

### Step 4: Clean grep

Run `grep -r "deploy_service" teleclaude/ --include="*.py"` — zero results.
The old system is fully removed.
