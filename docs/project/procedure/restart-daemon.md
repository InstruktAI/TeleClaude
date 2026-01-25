---
description: Controlled daemon restart with verification and log checks.
id: teleclaude/procedure/restart-daemon
scope: project
type: procedure
---

# Restart Daemon — Procedure

## Goal

- @docs/policy/daemon-availability

- Restart the daemon with minimal downtime and verify it is healthy.

- You are in the TeleClaude repository.

1. Run `make restart`.
2. Verify the service is running with `make status`.
3. Check recent logs with `instrukt-ai-logs teleclaude --since 10m`.
4. If the daemon is restarting repeatedly, review:
   - `~/.teleclaude/logs/monitoring/teleclaude-api-unlink.log`
   - `~/.teleclaude/logs/monitoring/teleclaude-sigterm-watch.log`

- Daemon process restarted and confirmed healthy.

- If the daemon fails to start, review logs and revert recent changes.

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
