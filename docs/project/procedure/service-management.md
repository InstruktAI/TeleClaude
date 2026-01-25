---
id: procedure/service-management
type: procedure
scope: project
description: Standard commands for managing the TeleClaude daemon service.
---

# Service Management — Procedure

## Goal

- Manage daemon lifecycle safely and consistently.

- You are in the TeleClaude repository.

1. Start service: `make start`.
2. Stop service (emergency only): `make stop`.
3. Restart service after changes: `make restart`.
4. Check status: `make status`.
5. Review logs: `instrukt-ai-logs teleclaude --since 2m`.

- Service state updated and verified.

- If the daemon crash-loops, use `make stop`, inspect logs, and fix the root cause before restarting.

- TBD.

- TBD.

- TBD.

- TBD.

## Preconditions

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
