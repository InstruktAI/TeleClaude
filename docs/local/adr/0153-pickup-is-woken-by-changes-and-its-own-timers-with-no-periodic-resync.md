---
visibility: internal
number: 0153
date: 2026-10-31
description: The lifecycle runner is woken only by the changes it decides on and by per-project timers for scheduled tasks and failed-start retries; it keeps no periodic resync, not even a slow one, because every change it decides on now has an event of its own and a periodic pass would hide the next wake that goes missing.
---

# Pickup is woken by changes and its own timers, with no periodic resync — ADR

## Context

The lifecycle runner was woken by local todo and session events and, on top of
those, by a minute tick that ran a pass for every project checkout on the
computer. Each tick re-read every project's declaration and every project's
work, whether anything had changed or not. The tick also covered changes that
woke nothing else: a claim released on a GitHub-backed project's active
computer, a removal that frees the todos depending on it, a computer becoming
active, a scheduled task coming due, a start that failed, changes another
computer wrote to the shared record, and wakes dropped while the daemon
drained.

The person running the platform had set the direction that periodic scans
stop and that a change triggers the work, the way a cache invalidation
triggers a refresh, and doubted that missed events warrant a fallback.

The comparable production design, the Kubernetes controller pattern as
implemented by controller-runtime, is level-triggered: a reconcile request
names an object, a work queue de-duplicates identical requests, and
`RequeueAfter` schedules time-based work. It also keeps a periodic resync that
re-queues every object on a long interval as a safety net for missed events.

## Decision

Pickup adopts the controller pattern's level-triggered pass, per-project
de-duplication and requeue-after timers, and keeps no periodic resync.

Every change pickup decides on emits a wake for its project: the existing
local todo and session events, the todo-updated event for a cleared claim, a
removal, a reactivation and every item a store refresh adopts, and an event
naming a computer active. Scheduled tasks and retries of failed starts are
per-project timers rebuilt from the work record. The daemon evaluates every
project it serves once at start. Nothing re-queues projects on an interval.

## Consequences

- A computer where nothing happens runs no pickup and re-reads no project's
  declaration.
- A wake that a future change forgets to emit is not covered by a later scan:
  the work it concerns waits for the next change in that project. Such a gap
  shows up as work not starting, where a periodic resync would have hidden it
  for up to one interval.
- A GitHub delivery that never arrives leaves the change it carried waiting
  for the project's next delivery or the GitHub store's own refresh, which
  keeps its own duties and interval.
- Restart continuity rests on the daemon-start pass, not on replaying the
  wakes that arrived while the daemon drained.

## Alternatives Considered

- **Keep the minute tick.** It covers every missing wake within a minute, at
  the cost of a full scan of every project every minute on every computer, and
  it is the scan the platform had decided to stop.
- **Replace the tick with a slow resync,** as controller-runtime does. It
  costs little, but it is the fallback that was judged unwarranted, and it
  would turn every missing wake into a delay of up to one interval that nobody
  notices instead of a failure that is found and fixed.
- **Adopted changes re-announce the events they amount to** — a phase
  advanced, a todo delivered — instead of one todo-updated event per adopted
  item. Pickup is level-triggered, so the event type changes nothing it
  decides, and re-announcing acts already taken on another computer would
  present them as new to every other consumer of those events.
