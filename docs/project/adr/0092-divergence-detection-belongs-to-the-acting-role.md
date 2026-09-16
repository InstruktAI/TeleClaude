---
visibility: public
number: 0092
date: 2026-09-16
description: Marker-divergence detection runs inside the role that repairs it, replacing an unattended periodic sweep that faulted to a log.
---

# Divergence Detection Belongs To The Acting Role — ADR

## Context

A daemon maintenance task walked the working tree of every registered project on a
timer, compared documentation markers against todo status, and emitted one
`ERROR` per finding carrying `assigned_owner="integrator"`.

That owner field appeared exactly once in the codebase, at the logging call.
Nothing dispatched to the named role, and nothing notified it. The findings
landed in the daemon log — the same channel the `log-check` obligation requires
agents to read and judge — describing a condition no actor had been sent to fix.
A recurring `ERROR` nobody can action trains its readers to skip it, and under a
test moratorium that log is the primary verification surface.

The sweep also judged shared state on a timer with no transaction boundary.
Delivery has a window in which a todo is settled and its fold has not yet
committed; the sweep faults there, correctly by its own predicate and wrongly in
fact, because the operation is still in flight. Because it only logged, this was
noise. The same predicate with an actuator would have corrected work in progress.
An agent did act on those findings out of band, in territory it did not own,
which is the outcome the design invites.

Separately, a code task classifying documentation state as a fault is machinery
grading semantic content.

## Decision

An unattended periodic sweep is not a sanctioned mechanism in this platform.
Detection of documentation-marker divergence runs inside the role that can act on
what it finds — the integrator, at its own integration entry, scoped to its own
project — and what cannot be folded automatically is handed to that role as an
agent-facing anomaly rather than written to a log.

Detection covers every settled status. Automatic repair remains narrower than
detection: only a delivered slug has a defined terminal fold, so a slug settled
by any other route is reported and left untouched for the role to resolve.

## Consequences

Detection is now conditional on integration being invoked for a project, where
the timer ran unconditionally. A project whose integrator never runs is not
scanned. This is accepted: an unscanned project is visibly unattended, whereas
the timer produced findings that looked attended and were not.

Findings now reach an actor. They are re-derived at each integration entry, so
they persist while the condition holds and disappear when it clears, without
accumulating in a channel that cannot clear them. They do not block the drain: a
path is most often unfoldable because another session holds it dirty, and halting
integration does not release it.

Automatic repair is deliberately incomplete. A slug settled as removed or a
holder still requires a human-or-agent judgement, because guessing a fold moment
could rewrite documentation in a direction nobody asked for. A wrong fold is
worse than an unfolded one.

The `ERROR` stream from the timer is gone, restoring the log's value as evidence.

## Alternatives Considered

**Keep the sweep and give it a real dispatch.** Rejected: it does not address
judging shared state on a timer with no transaction boundary, and an actuator on
that predicate is more dangerous than the logging was.

**Keep the sweep and lower its severity.** Rejected: severity was never the
defect. A finding nobody owns is noise at any level.

**Widen automatic repair to every settled status.** Rejected: the terminal fold
is defined for delivery only. Inventing one for other statuses trades a visible
gap for silent corruption.
