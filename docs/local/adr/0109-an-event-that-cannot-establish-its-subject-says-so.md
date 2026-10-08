---
visibility: internal
number: 0109
date: 2026-10-01
description: An event's subject has three values — a registered home, none when the event concerns no registered home, or unknown when the subject cannot be established — so a missing fact is never read as a claim, and events from computers that predate the subject read as unknown.
---

# An Event That Cannot Establish Its Subject Says So — ADR

## Context

ADR-0105 made an event's subject the fact that access, subscriptions and
procedure activation key on. It gave the subject two values: a registered home,
or none when the event is about the platform itself. It also read events from
computers that predate the subject as having none.

Tracing each producer's subject rule showed that "none" was carrying three
different facts. Some events are about the platform itself: daemon and stream
health, node presence, the schedule clock. Some concern no registered home
without being about the platform, such as a session working in a folder no
registration governs. And some do not know their subject at all: an event about
a todo whose project declaration cannot be read on the emitting computer, or an
event from a computer that predates the subject. Every consumer reading "none"
would treat all three as one claim.

The fleet's cross-version contract (ADR-0026) requires that a node lacking a
fact never silently does the wrong thing. The subject owner had already met this
shape: an owner the emitting computer cannot read is unresolved, never no owner.

## Decision

- **The subject has three values.** A registered project, person or company; none
  when the event concerns no registered home; or unknown when the subject cannot
  be established.
- **None is a claim.** It states that the event concerns no registered home,
  whether the platform itself or work no registration governs. A producer states
  none only when that is true of its act.
- **Unknown is the absence of the claim.** A producer that acted on something
  belonging to a registered home, but cannot establish which home on the
  emitting computer, states unknown, never none and never a guessed home.
- **Older events read as unknown.** An event from a computer that predates the
  subject carries no claim about it, so a computer that knows the subject reads
  it as unknown, not as none.

## Consequences

- A consumer that relies on the subject can trust none, and can leave an event
  with an unknown subject alone instead of acting on a mislabelled one.
- Receiving-side reach needs no new rule: data a receiver cannot place already
  reaches only admins and the system principal.
- Existing consumers that ignore the subject keep processing every event as
  before, including events with an unknown subject.
- Every subject-reading consumer must handle a third value, and a producer
  deriving its subject must tell "concerns no home" apart from "could not
  establish the home".
- While the fleet spans versions, events from older computers carry an unknown
  subject. Anything keyed on the subject, such as per-subject correlation, sees
  those events under unknown rather than under their real home until those
  computers upgrade.

## Alternatives Considered

- **Keep two values and read missing subjects as none.** Rejected: it turns an
  absent fact into a false claim that the event concerns no home, and consumers
  keyed on none would act on events about real homes.
- **Separate "about the platform" from "no registered home" as two further
  values.** Rejected: no consumer decides differently between them. Both concern
  no home that a principal could hold, so one value carries both truthfully.
- **Have a newer computer infer the subject of an older event from its
  payload.** Rejected: inference from a payload is a guess dressed as a fact,
  which is the failure this decision removes.

## Status

Superseded in part by ADR-0114: the three values this decision gave the subject
belong to the event's `home`, and `subject` names the one thing the event is
about. The rest of the decision stands for the home.

Superseded in part by ADR-0118: the three values belong to the event's origin; an event states no home.
