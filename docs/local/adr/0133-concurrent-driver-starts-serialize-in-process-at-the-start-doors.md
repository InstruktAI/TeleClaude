---
visibility: public
number: 133
date: 2026-10-26
description: Lifecycle orchestrator starts for one todo on one computer pass the live-holder check and the creation or claim it admits one at a time, under an in-process critical section keyed by project and todo that records no state.
---

# Concurrent Driver Starts Serialize In-Process at the Start Doors — ADR

## Status

Superseded in part by ADR-0134: a start that finds another start of the same
todo inside the section is refused at once, naming that start's session, instead
of waiting for it. The in-process section per project and todo is unchanged and
remains accepted.

## Context

ADR-0052 made the session registry the authority on whether a live
orchestrator already drives a todo, and ADR-0078 retired the short-lived
dispatch claim that bridged the gap between deciding to start a driver and the
started session being recorded. ADR-0078 records that the platform does not
serialize concurrent start attempts and that no replacement TTL, lock,
reservation, inactivity fallback or dedup store is introduced.

Each start door therefore checks for a live holder and then creates or adopts
the driver as two separate steps with nothing held between them: the session
create doors, through which the lifecycle runner, a manual lifecycle start,
`telec sessions run` and the TUI all start drivers, and the in-process adoption
a lifecycle operation performs for its calling session. The lifecycle router is
serial within itself, but every other door runs concurrently with it on the
daemon's event loop. Two starts for one todo that both pass the check before
either has recorded its driver each produce a driver. Duplicate orchestrators
blocked each other, left a todo undriven, and filed one bug twice; ruling that a
second live driver must never be possible makes closing that window a
requirement rather than an accepted gap.

The holder signal spans two stores: the session registry and the todo's
`active_runner`, which lives in the project's workflow store and may be the
GitHub store's working copy. Every door on one computer runs in the one daemon
process. The procedure activation runner already serializes its resolve-or-create
per procedure and home with an in-process critical section, and a hand start of
a standing agent takes the same one.

## Decision

On one computer, a lifecycle orchestrator start for a todo holds an in-process
critical section keyed by the todo's canonical project state root and slug
across its live-holder check and the creation or claim that check admits. The
key carries no lane: the live-holder check already admits one driver per todo
whatever lane is asked for, so starts in different lanes contend for the same
holder and must be decided one at a time too. The create doors take the section
for an orchestrator launch created on this computer; the in-process adoption
takes it for its check and its ownership writes. A start that finds a holder
inside the section is refused naming that holder. The section records nothing,
outlives no request, and leaves the registry and `active_runner` as the only
ownership facts.

## Consequences

- Concurrent first starts for one todo on one computer yield one orchestrator,
  whichever doors they arrive through; the losers are refused naming it.
- No ownership state is added: a failed start, a crash or a restart leaves
  nothing to release, expire or reconcile, and ADR-0078's retirement of
  time-bound reservations stands.
- A start waits while another start of the same todo is inside the section,
  including while an adoption writes `active_runner` to a GitHub-backed store.
  Starts of different todos never wait on each other. The wait is bounded below
  the callers' request deadline, and a start that exceeds it is refused.
- A start must not hold the section while it calls another door, because the
  door would wait on the section its caller holds. A lifecycle dispatch therefore
  takes no section of its own; the create door it calls takes it.
- The guarantee holds only inside one daemon. Two computers that see one todo
  through a shared workflow store are not serialized by it.

## Alternatives Considered

- **A conditional write at the ownership record.** Making the claim atomic where
  it is stored would need one transaction across the session registry and the
  workflow store, which are separate stores, the latter possibly a GitHub working
  copy with no compare-and-set. Writing `active_runner` from every create door
  would also restore the multi-writer link ADR-0052 rejected.
- **Reinstating a dispatch reservation.** Rejected for ADR-0078's reasons: it is
  a second, expiring ownership state with acquisition, expiry and cleanup paths.
- **Leaving the window open and repairing duplicates afterwards.** Rejected: a
  duplicate driver acts before any repair can observe it, and the outcome
  required is that a second driver never exists.
