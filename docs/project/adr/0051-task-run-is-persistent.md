---
visibility: public
number: 0051
date: '2026-06-18'
description: 'A /next-run-task session is persistent — it executes against the durable task-plan, records to the log, delivers to the workspace, and stays alive for human follow-up and subsequent scheduled firings; the lifecycle runner wakes the live session on each due tick rather than spawning a fresh ephemeral run. Supersedes ADR-0042 §5 (ephemeral-and-terminate); the rest of ADR-0042 stands.'
---

# ADR-0051: Task Runs Are Persistent, Not Ephemeral — ADR

## Context

`project/adr/0042-task-lane-decoupled-recurring-self-bookkeeping` §5 decided that
each task firing is an ephemeral session that reads, executes, records, and
terminates, with the `log` carrying continuity across otherwise-memoryless firings.

In delivery, a task run is the operator's live window into what a standing intent is
doing: a terminated session leaves no surface to inspect mid- or post-firing, and the
session list cannot show a running task as a standing beacon. The requirement is that
`/next-run-task` stay alive. That conflicts with ADR-0042 §5's ephemeral-and-terminate
stance, and this record captures the reversal.

## Decision

A `/next-run-task` session is **persistent**. It executes its firing against the
durable `task-plan`, records to the `log`, delivers outputs to
`{project_root}/workspace/<slug>/`, and **stays alive for human follow-up; it never
self-ends**.

- For a **recurring** task, the lifecycle runner wakes the existing live run session
  on each due `scheduler.tick.*` instant (it signals the session it already owns)
  rather than spawning a fresh session. The run's dispatch-claim / `active_runner`
  link keeps exactly one run session per task.
- For a **one-shot** task, the session executes its single firing and then waits,
  available for inspection.

The `log` remains the continuity and restart-idempotency record, but its discipline
narrows to **start-of-life** — a fresh dispatch or a post-restart revival reads the
`log` to avoid repeating a completed firing. A live session is not memoryless across
its own firings.

This supersedes ADR-0042 §5 only. ADR-0042's decoupling of the task lane from the
SDLC prepare machine, the human authorization gate, recurrence via `schedule`, the
`log`, and the durable workspace all stand.

## Consequences

- A task that has fired always has a live, inspectable run session — a standing
  beacon in the session list, consistent with `general/principle/session-lifecycle`.
- Recurrence is delivered by waking the live session per tick, so the runner's
  `ALREADY_DRIVEN` suppression and dispatch-claim dedup keep one run session per
  task; the tick signals the live session instead of producing a duplicate dispatch.
- Persistent sessions hold a live session for the life of the task. This is the
  accepted cost of an always-inspectable run surface; like other manually-started or
  adopted sessions, a task run is excluded from the auto-dispatch concurrency cap.
- The `log`-first discipline is unchanged in purpose (idempotent resumption) but
  applies on revival, not on every firing.

## Alternatives Considered

- **Ephemeral per-firing runs (ADR-0042 §5).** Rejected here: a terminated run leaves
  no live surface for the human to inspect, which is the explicit operator
  requirement for the task lane. Continuity that ephemerality bought through the
  `log` is retained — the `log` still bridges restart revivals.

## Status

Superseded in part by ADR-0060. A one-shot firing now delivers-and-ends on success and
holds on error, so the "never self-ends" stance narrows to the error-beacon and
recurring cases; the recurring wake-the-live-session decision stands.
