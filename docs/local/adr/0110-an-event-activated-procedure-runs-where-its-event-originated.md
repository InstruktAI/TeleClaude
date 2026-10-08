---
visibility: internal
number: 0110
date: 2026-10-03
description: An event-activated procedure runs on the computer its event originated on, in the home its subject names, with platform events answered in the platform's own checkout; a computer that merely shares the home never runs the same work.
---

# An Event-Activated Procedure Runs Where Its Event Originated — ADR

## Context

Procedure activation starts or wakes a procedure's standing agent when an event
it subscribes to arrives. Its first form listened only to company-stamped
inbound webhooks, and every computer that hosted the event's company started
its own agent. Two facts made that placement wrong.

Development and stable computers commonly configure the same projects, people,
and companies. Under per-host activation, one event made both computers do the
same work for the same home, with no way for either to know the other had.

ADR-0105 gave every event on the platform stream its origin computer and its
subject, as facts the producer states, and left each consumer to decide its
own reaction on the receiving side. ADR-0109 made the subject distinguish a
registered home, none, and unknown. Distribution stays the producer's choice:
an event published locally or to the cluster reaches the consumers its
transport delivers to, and a consumer may receive events that happened on
another computer.

## Decision

- **Origin chooses the executing computer.** Only the computer an event was
  emitted on activates the procedures it matches. A computer that receives the
  same event and shares the home does nothing for it.
- **Subject chooses the home.** A company, person, or project subject runs its
  procedures in that company's home, that person's folder, or that project's
  checkout on the origin computer. An event whose subject is none is a platform
  event and runs its procedures in the platform's own checkout there.
- **Absence is reported, never rerouted.** A home that does not exist on the
  origin computer fails the activation visibly. No other computer and no other
  home takes the work.
- **Unknown activates nothing.** An event with an unknown origin or an unknown
  subject starts no standing agent.
- **The consumer adds no transport.** Activation reacts only to events that
  reach it. It neither changes how producers distribute events nor elects,
  fails over, or coordinates computers.

## Consequences

- One event yields one activation per matched procedure, however many computers
  configure its home.
- A computer that is not running when its event is emitted, or that does not
  hold the named home, misses that activation. Recovery belongs to the
  procedure's own reconciliation and periodic activation, as for any missed
  event.
- Work concerning a home is done where the event about it happened. An operator
  who wants a home's procedures to run on one computer runs the producing work
  there.
- Platform procedures run beside the platform's code on whichever computer
  emitted the platform event, so each computer answers its own platform events.
- Retiring per-host activation removes the dependence on each computer's
  hosting answer; the activation path now consults the home only on the origin
  computer.

## Alternatives Considered

- **Every computer hosting the home activates.** Rejected: identical work runs
  once per hosting computer, and the duplicates cannot see each other.
- **An elected or designated executor per home.** Rejected: it adds fleet
  election and failover machinery for a decision the event already carries.
- **The producer addresses the executing consumer.** Rejected: ADR-0105 keeps
  producers from deciding anything about their consumers.

## Status

Superseded in part by ADR-0114: the event's `home`, not its `subject`, names the
home a procedure runs in. The rest of the decision stands.

Superseded in part by ADR-0118: the event's origin, which states no home, decides the activation; the consumer resolves the home a procedure runs in from that origin on the emitting computer.
