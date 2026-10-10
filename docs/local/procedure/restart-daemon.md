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

<!-- planned-change:restart-never-strands-daemon -->

1. Run `make restart` as the final action of the sequence. Nothing follows it in the same sequence, and its success means only that the running daemon was prepared and the service manager accepted the restart (`local/projects/teleclaude/policy/daemon-availability`).

<!-- change:restart-never-strands-daemon -->

1. Run `make restart` as the final action of the sequence. Nothing follows it in the same sequence, and its success means only that the running daemon was prepared and the service manager accepted the restart, or that the restart was deferred to the draining daemon (`local/projects/teleclaude/policy/daemon-availability`).

<!-- /planned-change:restart-never-strands-daemon -->

## Outputs

<!-- planned-change:restart-never-strands-daemon -->

- The running daemon was prepared and the service manager has accepted the restart.

<!-- change:restart-never-strands-daemon -->

- The running daemon was prepared and the service manager has accepted the restart, or the draining daemon owns completing it.

<!-- /planned-change:restart-never-strands-daemon -->

## Recovery

<!-- planned-change:restart-never-strands-daemon -->

- A refused restart is reported by `make restart` itself: a non-zero exit carrying the refused or incomplete preparation that withheld the service-manager action, or the service manager's own output.
- An incomplete preparation leaves the same daemon draining. Running `make restart` again observes that daemon until its acknowledged work settles (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`).

<!-- change:restart-never-strands-daemon -->

- A refused restart is reported by `make restart` itself: a non-zero exit carrying the refused machine configuration or refused preparation that withheld the service-manager action, or the service manager's own output.
- A deferred restart owes nothing further: the draining daemon completes it once its acknowledged work settles (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`).

<!-- /planned-change:restart-never-strands-daemon -->

- A daemon that does not support preparation is reported as unsupported. Its first activation of the preparation protocol follows the explicit legacy activation path in `local/projects/teleclaude/policy/agent-service-control`.

- Why a restart was refused, and whether a restarted daemon came back healthy, are separate questions, never a continuation of the restart sequence. Each is answered on demand with `make status` and recent logs (`instrukt-ai-logs teleclaude --since 10m`). If the daemon is restarting repeatedly, review the process-reaped event stream (`telec events`) and the structured SIGTERM/shutdown logs before taking action; if it fails to start, review logs and revert recent changes.
