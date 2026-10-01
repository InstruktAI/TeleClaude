---
visibility: public
number: 0075
date: 2026-08-12
description: A rework whose cutover must be seeded before any new-code emission is delivered unified; coherence, not file count, decides whether it is partitioned.
---

# Cutover-Bearing Delivery Is Not Partitioned — ADR

## Context

The authored-session-delivery rework replaces a text-authoritative peer carrier
with a structured one and introduces four durable surfaces at once: structured
peer segments, accepted-turn bindings with ordered authored parts, output
generations bound to turn identity, and Discord send intents.

The conversation-delivery architecture requires that startup migration record a
runtime-qualified cutover reference and one immutable legacy generation per
existing adapter before adapters, pollers, or conversation delivery emit
new-code output. It names the inverse — lazy cutover seeding letting new output
enter state later claimed as legacy — as a failure mode. The database contract
and the session-revival contract each name all four surfaces inside one
obligation, and the daemon-lifecycle contract binds the ordering to staged
startup.

A behaviour-partitioned decomposition of this rework was attempted and reversed
before any of it shipped. Two structural facts surfaced during that attempt: the
design contract for the rework is a wholesale companion document, which one
owner replaces in full and two owners cannot divide, and one projection contract
block could only be divided by cutting it at a section boundary.

Readiness rules prefer small changes and prescribe decomposition when a change
grows past one. They also fix how that judgment is made: size is estimated in
lines of change rather than files touched, and a decomposition is warranted only
when its parts each carry standalone value, never when it would leave a
half-working codebase. Those two clauses can point in opposite directions, and
this rework is a case where they do.

## Decision

A rework whose cutover must be seeded before any new-code emission is delivered
as one unified change. It is not partitioned, and file count is not evidence
that it should be.

Where the readiness rules' size clause and coherence clause conflict, coherence
governs. A decomposition that satisfies the size clause while producing a part
that carries no usable behaviour has not satisfied readiness; it has relocated
the problem and added a retro-seeding window the architecture forbids.

## Alternatives Considered

**Behaviour-partitioned decomposition** — one part per behaviour: peer carrier,
turn bindings, output generations, presentation. Rejected: each part emits
new-code output before the surfaces belonging to later parts are seeded, which is
precisely the lazy-seeding failure mode the architecture names. The cutover would
be seeded in instalments, and later parts would retro-seed state that earlier
ones had already written.

**Cutover-first decomposition** — a first part carrying all four schemas plus the
startup seeding, with behaviour layered on top. This satisfies the cutover
invariant and was the stronger of the two alternatives. Rejected on two grounds.
The schema-and-seeding part is inert: it changes no observable behaviour on its
own, which is the case the coherence rule excludes. And the wholesale companion
cannot be divided — whichever part carries it publishes contract text describing
behaviour the other parts have not built, leaving a live contract that
misdescribes the system, so the already-reviewed contract bodies would have to be
re-authored into a different decomposition for no behavioural gain.

## Consequences

**Positive.** The cutover is seeded once, in one act, before anything emits, so
no window exists in which new-code output can later be misclassified as legacy.
The reviewed contract bodies stay as reviewed. The delivery is coherent: at no
point does a partially-migrated carrier sit in the mainline with some consumers
converted and others not.

**Negative, and real.** The change is large, and this decision accepts that size
rather than reducing it — a departure from the small-change default the readiness
rules hold. More code changes at once, so a defect surfaces against a wider
surface than a partitioned change would expose, and reverting the change reverts
all of it, including the parts that were correct. The decision also concentrates
risk in the cutover itself: seeding once means one act must be right, with no
earlier partial landing to prove it against.
