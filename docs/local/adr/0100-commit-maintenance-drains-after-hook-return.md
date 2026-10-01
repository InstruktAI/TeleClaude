---
visibility: internal
number: 100
date: 2026-09-24
description: Let Git return after recording commit-boundary maintenance, while one-shot contenders drain the owed work in order.
---

# Commit Maintenance Drains After Hook Return — ADR

## Context

ADR-0087 moved deterministic maintenance from agent checkpoints into Git hooks so every canonical-main advancement receives the actions its changed paths owe. The hook then waited for installation, publication, Blueprint regeneration, and service restart to finish. A commit could be recorded quickly while the Git command remained occupied for minutes by post-commit work.

The fork was whether the Git invocation should wait for maintenance to finish, or return after making the owed work durable. The latter had to preserve automatic execution for a person committing without an agent session, ordered actions, and a visible path for failures. A daemon-owned background task was a poor fit for a maintenance action that restarts that same daemon.

## Decision

The hook records the actions owed by an immutable canonical-main activation, starts a one-shot contender when it records work, and returns without waiting for the actions. Each owed action has a gitignored record keyed by the activated tip and action id. A contender waits on an OS-owned file lock, drains outstanding activations in Git ancestry order and actions in their declared precedence order, then exits. Every hook that enqueues work starts a contender, including when another contender already holds the lock; the waiting contender covers an enqueue that arrives during the active drain's final scan.

This is Git-triggered machine maintenance rather than an API `InternalCommand` with a caller. The per-action records are its durable accountability surface; no caller operation receipt is manufactured for an unattended hook.

A confirmed success removes its action record. A terminal failure remains recorded and is reported through structured logs for operational investigation. An interrupted attempt remains retryable when a later contender runs. Actions must converge safely when repeated because an effect can complete immediately before the success record is removed. No completion notification is sent to the committer.

## Consequences

- Git command duration no longer includes the heavy post-commit actions. The commit still records before maintenance and its validation gate remains blocking.
- Pending files answer which actions remain owed; structured terminal records answer what each attempt did. A stale or failed file is visible to operational anomaly detection.
- An OS file lock needs no PID-liveness protocol or cleanup after a crash. Lock-file existence carries no ownership meaning.
- Overlapping commits can create short-lived waiting contenders. They acquire the lock in turn, find no work after an earlier contender drained it, and exit.
- A later agent log check can precede maintenance completion. It cannot serve as terminal evidence for an action still pending; delayed maintenance failures are reported through the action record and structured logs.
- A host failure can leave action records pending until a later hook invocation or operational recovery starts another contender. Automatic always-on replay is not part of this decision.

## Alternatives Considered

- Keep maintenance synchronous inside the hook. This preserves immediate terminal evidence but makes every committer wait for unrelated installation, publication, and restart work.
- Suppress new contenders while a runner PID appears alive. A hook can enqueue after the runner's last scan, observe that PID, and exit just before the runner does, leaving its work stranded. PID reuse and stale files add further ambiguity.
- Run maintenance as a daemon-owned background operation. Restart is one of the maintenance actions, so the daemon can terminate its own executor before it records or completes that action.
