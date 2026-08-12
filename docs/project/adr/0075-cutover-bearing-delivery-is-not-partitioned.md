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

Readiness rules require work that fits a single builder session and prescribe
splitting when it does not. They also fix how that judgment is made: size is
estimated in lines of change rather than files touched, and a split is warranted
only when the pieces are independently shippable and independently valuable,
never when it would leave a half-working codebase. Those two clauses can point
in opposite directions, and this rework is a case where they do.

## Decision

A rework whose cutover must be seeded before any new-code emission is delivered
as one unified change. It is not partitioned, and file count is not evidence
that it should be.

Size is therefore not carried by partition. It is carried by the resumability
the build contract already provides, which is stated where that contract lives
and is not restated here.

Where the readiness rules' size clause and coherence clause conflict, coherence
governs. A split that satisfies the size clause while producing a slice that
ships nothing usable has not satisfied readiness; it has relocated the problem
and added a retro-seeding window the architecture forbids.

## Alternatives Considered

**Behaviour-partitioned decomposition** — one slice per behaviour: peer carrier,
turn bindings, output generations, presentation. Rejected: each slice emits
new-code output before the surfaces belonging to later slices are seeded, which
is precisely the lazy-seeding failure mode the architecture names. The cutover
would be seeded in instalments and later slices would retro-seed state that
earlier slices had already written.

**Cutover-first decomposition** — a first slice carrying all four schemas plus
the startup seeding, with behaviour layered on top. This satisfies the cutover
invariant, and it was the stronger of the two alternatives. Rejected on two
grounds. The schema-and-seeding slice is inert: it is shippable but carries no
value on its own, which is the case the coherence rule excludes. And the
wholesale companion cannot be divided among the slices — whichever slice
carries it publishes contract text describing behaviour the other slices have
not built, leaving a live contract that misdescribes the system, so the
already-reviewed contract bodies would have to be re-authored into a different
decomposition for no behavioural gain.

**Seeking an authorization to exceed the readiness gate.** Rejected because no
such authorization exists. The readiness rules provide risk acceptance only for
a declared emergency hotfix, which this is not. Treating the conflict as
awaiting a signature stalls work on a permission the rules never define; the
conflict resolves technically, within the rules themselves.

## Consequences

**Positive.** The cutover is seeded once, in one act, before anything emits, so
no window exists in which new-code output can later be misclassified as legacy.
The reviewed contract bodies stay as reviewed. The delivery is coherent: at no
point does a partially-migrated carrier sit in the mainline with some consumers
converted and others not.

**Negative, and real.** The change is large, and this decision accepts that
size rather than reducing it — a departure from the single-session ideal the
readiness rules hold as their default. The review surface is correspondingly
wide, and a defect found late is found against more code than a partitioned
delivery would expose. Rollback is coarse: reverting reverts all of it,
including the parts that were correct. Because size is carried by resumability
rather than removed, this decision makes the delivery's tractability depend on
that mechanism holding; where it does not, the cost scales with the size
accepted here.
