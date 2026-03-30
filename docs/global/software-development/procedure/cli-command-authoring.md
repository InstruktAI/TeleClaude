---
description: 'Procedure for adding new CLI commands to telec: REST model, surface registration, handler, API endpoint, tests.'
id: 'software-development/procedure/cli-command-authoring'
scope: 'domain'
type: 'procedure'
---

# CLI Command Authoring — Procedure

## Goal

Add new CLI commands to `telec` consistently, following REST resource conventions and the established handler/surface/API pattern.

## Steps

1. **Define the REST resource model.** Use nouns with action subcommands: `artifacts {list|read|write}`, not verbs like `read-artifact`. Group related actions under a parent.

2. **Register in `CLI_SURFACE`.** Add a `CommandDef` entry in `teleclaude/cli/telec/surface.py` with description, args, flags, auth, and examples. This is the canonical surface definition.

3. **Write the handler.** Add a function in the appropriate `teleclaude/cli/telec/handlers/` module. Handlers parse args, call the daemon API via `tool_api_request()`, and print output. Handlers are sync.

4. **Add the API endpoint** (if daemon-backed). Add a route in `teleclaude/api/` (e.g., `todo_routes.py`). Use FastAPI path/body params. Return `{"status": "ok", ...}` on success.

5. **Route the subcommand.** Wire the handler into the dispatcher function (`_handle_todo`, `_handle_roadmap`, etc.) with the appropriate subcommand string match.

6. **Update `__all__` exports.** Add the handler to the module's `__all__` list.

7. **Write TDD tests.** RED first, then GREEN. Test handler arg parsing and API integration. Use real DB fixtures where possible, not mock theater.

8. **Evaluate `@exec` expansion.** Only add to `telec-cli.md` tool spec with 100% certainty of global need. Most commands do not need `@exec`.

9. **Add to `Required tools`** in relevant lifecycle procedure docs if the command is procedure-scoped.

10. **Deploy.** Run `telec sync` to rebuild indexes and deploy artifacts.

11. **Verify.** `make restart && make status` for daemon-backed commands. Smoke test the full flow.

## Error handling

`ToolAPIError` is caught at the CLI entry point (`teleclaude/cli/telec/__init__.py`). Handlers never catch API errors — they propagate naturally.

## Response format

All API responses return `{"status": "ok", ...}` on success. Errors propagate as HTTP status codes with a `detail` field.

## Sync/async boundary

CLI handlers are sync. For direct DB access (no daemon), use `asyncio.run()` with full async init/close, or sync `TodosDb` methods (`read_state_sync`, `write_state_sync`, `deliver_sync`). Prefer daemon API calls over direct DB access.
