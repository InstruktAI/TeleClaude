---
description: Controlled daemon restart with verification and log checks.
id: teleclaude/procedure/restart-daemon
scope: project
type: procedure
---

# Restart Daemon — Procedure

## Goal

- @docs/project/policy/daemon-availability.md

- Restart the daemon with minimal downtime and verify it is healthy.

## Preconditions

- You are in the TeleClaude repository.

## Steps

1. Run `make restart`.
2. Verify the service is running with `make status`.
3. Check recent logs with `instrukt-ai-logs teleclaude --since 10m`.
4. If the daemon is restarting repeatedly, review:
   - `~/.teleclaude/logs/monitoring/teleclaude-api-unlink.log`
   - `~/.teleclaude/logs/monitoring/teleclaude-sigterm-watch.log`

## Outputs

- Daemon process restarted and confirmed healthy.

## Recovery

- If the daemon fails to start, review logs and revert recent changes.
