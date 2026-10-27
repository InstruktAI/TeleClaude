---
visibility: 'public'
number: '35'
date: '2026-06-11'
description: "A todo's lifecycle driver is owned by a durable session-id link the dispatcher writes, verified lazily against the live-session ledger — not inferred from session titles."
---

# ADR-0035: Active-runner driver ownership — ADR

## Context

The lifecycle runner must decide, before dispatching, whether a todo already has
a session driving its lifecycle, so it never spawns a duplicate driver. The only
mechanism available was an inference over session metadata: scan live sessions
for one whose title and worktree match the slug and lane. That inference is
fragile on three counts. A session's title is fixed at launch, so a session that
changes what it drives after starting becomes invisible to the scan. The match is
a heuristic over derived attributes rather than a recorded fact, so prefix
collisions and lane-boundary edge cases leak. And it couples the ownership
decision to agent-runtime session-naming conventions that exist for unrelated
reasons.

Separately, the bookkeeping that releases ownership when a driver ends is itself
fallible: the clear is a reaction to a session-close event, and an event can be
missed. Any ownership signal that is trusted as ground truth therefore risks a
permanent dispatch deadlock for a todo whose driver ended but whose ownership was
never cleared.

## Decision

Driver ownership is a durable, single-valued field on the Todo aggregate —
`active_runner` — holding **only** the driving agent session id, a
foreign-key-style link todo → session. Its presence is the entire "already
driven" signal; everything else (lane, command, liveness, project) is resolved by
dereferencing the session id against the agent-runtime session record, so the
session domain stays the single authority for session detail.

The **dispatcher is the sole writer**. Whoever spawns a lifecycle session records
the returned session id on the todo at spawn — the lifecycle runner for
autonomous dispatch, the manual-start command path for an operator-initiated
start. The state machine never writes it, and the driven session never asserts
its own ownership; ownership is established by the act of spawning, not claimed
from inside.

Ownership is released along two paths. The **eager** path is the workflow service
clearing the field on a pure session-id match when it consumes the
session-ended event — workflow mutates its own state, preserving
single-state-ownership rather than letting the close path reach into the todo
store. The **lazy** path is the runner verifying, at evaluation time, that a
non-null `active_runner` still names a live session in the ledger; a link to a
session that is no longer live is treated as stale, cleared in place, and the
todo is dispatched. The lazy path makes a missed eager clear self-healing instead
of fatal.

The short-lived dispatch claim keyed by `(project, slug, lane)` is retained for a
different job: it guards only the boot-gap race between deciding to spawn and the
spawned session becoming recordable. It hands off to `active_runner` for
steady-state ownership and is not the ownership signal itself.

## Consequences

- Ownership is an O(1) authoritative read of a recorded fact, not a scan-and-infer
  over session metadata; the title/worktree heuristic is retired from the
  ownership role (it remains available for unrelated needs such as routing
  feedback to a specific worker).
- A driver changing what lane it runs no longer breaks ownership, because the
  signal is the link's presence, not a launch-time title.
- A missed eager clear cannot deadlock dispatch: the next runner pass verifies
  liveness and heals the stale link. No separate repair sweep is needed.
- Single-state-ownership holds: workflow owns the field and clears it on event
  consumption; agent-runtime stays authoritative for session existence and
  detail.
- Two release paths must both be maintained, and the runner must dereference the
  session ledger to validate a link rather than trusting presence alone — a cheap
  read, but a required one.
- Manual operator starts must write `active_runner` at their own dispatch point,
  identical to the runner; an unmarked manually-started session would otherwise
  look undriven and be duplicated.

## Alternatives Considered

- **Session title/worktree scan as the ownership authority.** Rejected: it infers
  ownership instead of recording it, goes blind when a session changes lanes after
  launch, and is prefix-collision prone at slug boundaries.
- **Denormalizing lane/status onto the field alongside the session id.** Rejected:
  it copies session facts into the workflow store and creates two sources of truth
  for the same data; the bare link plus a dereference keeps one authority.
- **Trusting the eager close-event clear alone, with no lazy verification.**
  Rejected: a single missed close event would leave a stale link that permanently
  suppresses dispatch for that todo, with no path to recovery short of manual
  intervention.

## Status

Superseded in part by ADR-0078: time-bound dispatch claims are removed; the
active-runner ownership decision remains accepted. Superseded in part by
ADR-0135: a claim names its session's computer, the master records it for a
project on the GitHub store, and only the computer it names clears it as stale.
