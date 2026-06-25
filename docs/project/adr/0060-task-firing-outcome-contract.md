---
visibility: public
number: 0060
date: '2026-06-25'
description: "A task firing reports a durable outcome that the lifecycle runner reconciles into the todo's terminal state — success delivers a one-shot (records and stays live for a recurring), error holds with a reason and keeps the run session alive as the beacon. The outcome is a durable stamp on the lifecycle-runner + todo-state substrate, not an ephemeral event, and adds no new TodoState field; recovery from an error-hold is talk-to-stamp-success or a deliberate manual start, never a bare unhold. Supersedes ADR-0051 in part."
---

# ADR-0060: A Task Firing Reports a Durable Outcome Contract — ADR

## Context

`project/adr/0051-task-run-is-persistent` made a `/next-run-task` session persistent:
it executes, records to the `log`, and stays alive, never self-ending. That left the
task lane with no durable terminal completion signal. The dispatch guard for a one-shot
task is effectively "is this todo due AND is a run session alive": a one-shot's
schedule is perpetually due, and the only brake on re-dispatch is a live `active_runner`
(`ALREADY_DRIVEN`). Closing a finished run clears `active_runner` and does not record
that the firing completed, so the runner re-dispatches a fresh run of work that already
finished. The `log` carried continuity but is a narrative, not a queryable terminal
state, so it could not stop re-dispatch.

The lane needed a durable signal that a firing _completed_ and _how_, which the
stateless lifecycle runner could reconcile into a terminal state.

## Decision

A task firing ends by **stamping a durable outcome** on the todo, which the lifecycle
runner reconciles into the todo's terminal state on its next stateless re-evaluation:

- **success + one-shot** → the todo is **delivered** (terminal): the existing delivery
  path runs, the runner skips it via the `delivered` status, and its dependents are
  satisfied. The one-shot run session has no further role and ends.
- **success + recurring** → the firing is recorded, any prior error-hold is cleared,
  and the task stays live for its next scheduled instant (the runner wakes the existing
  session per ADR-0051).
- **error** → the todo is **held** with `hold_audit` recording the task-error source and
  the reason; the run session **stays alive as the inspectable beacon** for a human to
  engage, consistent with `general/principle/session-lifecycle`.
- **never stamped** (uncaught crash or kill) → no outcome is recorded and the firing
  stays re-runnable. The presence or absence of the stamp is the retry discriminator: a
  caught error holds; a silent death retries.

The outcome is a **durable stamp on the lifecycle-runner + todo-state substrate**, set
synchronously server-side so it persists regardless of the agent's fate after stamping.
It carries **no new `TodoState` field**: the terminal state _is_ the outcome —
`delivered` (success) and `hold` + `hold_audit` (error) already exist and are already
runner-respected.

An error-hold has **no bare-unhold recovery path**: a held error is recovered by
**talk → stamp success** (which delivers) or **kill → deliberate manual start**, never
by clearing the hold directly. The release surface refuses to clear a hold whose source
is the task-error source.

## Consequences

- A finished one-shot firing no longer re-dispatches after its run session closes — the
  defect this record resolves.
- An errored firing is durably held with its reason and is discoverable as a held todo
  even if the agent dies after stamping; it never silently re-dispatches a fresh,
  context-less run.
- A firing that crashes without stamping remains re-runnable, so a transient death
  retries while a caught error holds.
- One-shot runs now end on success and error-runs hold-and-wait, which **narrows**
  ADR-0051's "never self-ends" stance to the error-beacon and recurring cases. The
  recurring wake-the-live-session decision is unchanged.
- The release surface gains a guard: a task-error hold cannot be cleared by a bare
  release, so the recovery contract holds even from the operator surface.
- Unlike the jobs lane, no separate `last_status` / `last_error` record is kept: a
  one-shot task terminates and encodes its outcome in its terminal state, whereas jobs
  recur as config without a living session.

## Alternatives Considered

- **An ephemeral report event (the jobs-lane pattern).** Rejected for this lane: the
  lifecycle runner is a stateless re-evaluation engine over durable state, so an
  event-loss would reintroduce the duplicate-dispatch a durable stamp avoids. The stamp
  is the durable, task-lane-native equivalent of the jobs lane's report.
- **A new `TodoState.task_outcome` field.** Rejected: `delivered` and `hold` +
  `hold_audit` already express the terminal states and are already honored by the
  runner; a parallel field would duplicate terminal truth and invite divergence.
- **A server-emitted push notification on error.** Rejected in favor of the existing
  beacon: the persistent errored run session is already the human's inspectable surface
  (ADR-0051), and the durable hold is the discoverable record. Adding a cross-context
  notification event would expand the change beyond the task / lifecycle-runner lane.
