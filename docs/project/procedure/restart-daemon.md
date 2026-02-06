---
description: 'Controlled daemon restart with verification and log checks.'
id: 'project/procedure/restart-daemon'
scope: 'project'
type: 'procedure'
---

# Restart Daemon — Procedure

## Required reads

- @docs/project/policy/daemon-availability.md

## Goal

Restart the daemon with minimal downtime and verify it is healthy.

## Preconditions

- You are in the TeleClaude repository.

## Steps

1. Run `make restart`.
2. Verify the service is running with `make status`.
3. Check recent logs with `instrukt-ai-logs teleclaude --since 10m`.
4. If the daemon is restarting repeatedly, review:
   - `/var/log/instrukt-ai/teleclaude/monitoring/api-unlink.log`
   - `/var/log/instrukt-ai/teleclaude/monitoring/sigterm-watch.log`

## Outputs

- Daemon process restarted and confirmed healthy.

## Recovery

- If the daemon fails to start, review logs and revert recent changes.
