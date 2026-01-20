---
id: procedure/service-management
type: procedure
scope: project
description: Standard commands for managing the TeleClaude daemon service.
---

# Service Management

## Lifecycle Commands
- **Start**: `make start` (Enables and starts systemd/launchd service).
- **Stop**: `make stop` (Disables and stops service - EMERGENCY ONLY).
- **Restart**: `make restart` (Clean SIGTERM + start; use after code changes).
- **Status**: `make status` (Checks uptime and health).
- **Logs**: `instrukt-ai-logs teleclaude --since 10m` (View recent daemon logs).

## Development Rules
- ALWAYS use `make restart` for development; never stop the service manually.
- ALWAYS verify `make status` before reporting success.
- If the daemon crashes loopingly, use `make stop` to break the cycle and investigate logs.
