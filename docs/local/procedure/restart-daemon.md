---
description: 'Controlled daemon restart that ends when the service manager accepts it.'
visibility: 'public'
---

# Restart Daemon — Procedure

## Required reads

- @docs/local/policy/daemon-availability.md

## Goal

Restart the daemon with minimal downtime.

## Preconditions

- You are in the TeleClaude repository.

## Steps

1. Run `make restart` as the final action of the sequence. Nothing follows it in the same sequence, and its success means only that the service manager accepted the restart (`local/projects/teleclaude/policy/daemon-availability`).

## Outputs

- The service manager has accepted the restart.

## Recovery

- A refused restart is reported by `make restart` itself: a non-zero exit carrying the service manager's own output.
- Why a restart was refused, and whether a restarted daemon came back healthy, are separate questions, never a continuation of the restart sequence. Each is answered on demand with `make status` and recent logs (`instrukt-ai-logs teleclaude --since 10m`). If the daemon is restarting repeatedly, review the process-reaped event stream (`telec events`) and the structured SIGTERM/shutdown logs before taking action; if it fails to start, review logs and revert recent changes.
