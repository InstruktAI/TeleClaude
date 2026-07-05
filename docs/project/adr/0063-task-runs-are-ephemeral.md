---
description: 'A /next-run-task firing is ephemeral: it executes, records, stamps its outcome, and ends on success — recurrence is the lifecycle runner spawning a fresh run at each due scheduler tick, not waking a live session. Removes the persistent successful-run beacon and the runner-wakes-the-live-session signalling; the errored-firing hold-and-stay-alive beacon is retained. Supersedes ADR-0051; supersedes in part ADR-0060; restores ADR-0042 §5.'
date: '2026-07-05'
number: 63
visibility: 'internal'
---

# Task Runs Are Ephemeral, Not Persistent — ADR

## Context

`project/adr/0051-task-run-is-persistent` reversed ADR-0042 §5's
ephemeral-and-terminate stance: it made a `/next-run-task` session **persistent** so
the operator would have a live, inspectable "beacon" session per standing task, and it
delivered recurrence by having the lifecycle runner **wake the live run session** on
each due `scheduler.tick.minute` rather than spawning a fresh run.
`project/adr/0060-task-firing-outcome-contract` then narrowed that stance for one-shots
(success delivers-and-ends; error holds-and-stays-alive) but left the recurring
success case persistent-and-woken.

The persistent-beacon requirement was never an owner-authorized need. It reintroduced
long-lived sessions the platform's `general/principle/session-lifecycle` default
rejects (sessions are ephemeral; only a human-needed signal stays alive), and it built
a bespoke runner→live-session signalling path on top of that unrequested requirement.
The `ALREADY_DRIVEN` suppression the runner already applies to a live driver is enough
to prevent a concurrent second firing; nothing else needs to hold a task session open
on success.

## Decision

A `/next-run-task` firing is **ephemeral**. It executes its firing against the durable
`task-plan`, records to the `log`, delivers outputs to `{project_root}/workspace/<slug>/`,
stamps its outcome, and **ends on success** — it does not stay alive for follow-up or
for subsequent firings.

- **Recurrence is a plain minute-granular ticker.** A due recurring task is dispatched
  as a **fresh** `/next-run-task` at each due `scheduler.tick.minute` the runner
  evaluates, exactly like a one-shot. The runner never signals a live run session.
- **A live run session is only a brake.** While a firing runs, the runner's existing
  `ALREADY_DRIVEN` suppression (live `active_runner`) prevents a concurrent second
  firing. When no live run session exists at a due tick, the runner dispatches fresh.
- **A success ends the session.** A one-shot success delivers the todo (per ADR-0060)
  and the session ends; a recurring success records the firing (clearing any prior
  task-error hold), leaves the todo live for its next instant, and the session ends.
- **An errored firing is the only surviving live session.** An `error` holds the todo
  with the task-error source and stays alive as the human-inspection beacon — a
  legitimate blocked session under `general/principle/session-lifecycle`, not the
  persistence being removed. ADR-0060's durable-outcome contract and the no-bare-unhold
  recovery are unchanged.

The runner-wakes-the-live-session machinery and the persistent successful-run session
are removed. This restores ADR-0042 §5's ephemeral-and-terminate stance for the
success/recurring case.

## Consequences

- A finished successful firing leaves no live session; the session list shows only
  errored (held) task runs as standing beacons, consistent with the ephemeral
  session-lifecycle default.
- Recurrence flows through the normal `_resolve_kinded_dispatch` → task-run dispatch
  path gated by schedule eligibility; there is no separate per-tick signalling code.
- Because a live session only brakes while it runs and `task_schedule_due` matches the
  whole cron minute, a fast recurring firing on a sparse cron can be re-dispatched more
  than once within its matched minute. This is the accepted imprecision of a plain
  minute-granular ticker; no durable last-fired cursor is introduced.
- The `log` remains the continuity and restart-idempotency record, read at the start of
  each fresh firing (`general/principle/continuity`).

## Alternatives Considered

- **Keep the persistent beacon (ADR-0051).** Rejected: it encoded an unrequested
  operator-beacon requirement and reintroduced long-lived sessions the platform's
  session-lifecycle default rejects, plus bespoke signalling on top.
- **A durable last-fired cursor for exactly-once recurrence.** Rejected: for the
  intended coarse recurring schedules a plain ticker with the live-session concurrency
  brake is sufficient, and a cursor adds durable per-task state the lane deliberately
  avoids.
- **Deliver a recurring success (like a one-shot).** Rejected: `delivered` is terminal
  and satisfies dependents, which would end recurrence; a recurring success must leave
  the todo live for its next instant.
