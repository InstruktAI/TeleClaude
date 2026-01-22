---
id: procedure/service-management
type: procedure
scope: project
description: Standard commands for managing the TeleClaude daemon service.
---

## Goal

- Manage daemon lifecycle safely and consistently.

## Preconditions

- You are in the TeleClaude repository.

## Steps

1. Start service: `make start`.
2. Stop service (emergency only): `make stop`.
3. Restart service after changes: `make restart`.
4. Check status: `make status`.
5. Review logs: `instrukt-ai-logs teleclaude --since 2m`.

## Outputs

- Service state updated and verified.

## Recovery

- If the daemon crash-loops, use `make stop`, inspect logs, and fix the root cause before restarting.
