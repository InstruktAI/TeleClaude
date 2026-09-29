---
description: 'Controlled daemon restart that ends when the service manager accepts it.'
visibility: 'public'
---

# Restart Daemon — Procedure

## Required reads

- @docs/project/policy/daemon-availability.md

## Goal

Restart the daemon with minimal downtime.

## Preconditions

- You are in the TeleClaude repository.

## Steps

1. Run `make restart` as the final action of the sequence. Nothing follows it in the same sequence, and its success means only that the service manager accepted the restart (`project/policy/daemon-availability`).

## Outputs

- The service manager has accepted the restart.

## Recovery

- If `make restart` reports that the service manager refused the restart, run `make status` and read recent logs with `instrukt-ai-logs teleclaude --since 10m` to find why.
- Whether the restarted daemon came back healthy is a separate question, answered on demand by `make status` and recent logs. If the daemon is restarting repeatedly, review the `system.process.reaped` event stream (`telec events`) and the structured SIGTERM/shutdown logs before taking action; if it fails to start, review logs and revert recent changes.
