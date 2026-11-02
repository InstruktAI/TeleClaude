---
visibility: internal
number: 0155
date: 2026-11-02
description: A person-facing send that waits for an unreachable master is held as a durable operation on the requesting computer, whose row is both the held request and the caller's receipt, instead of an entry in the local Redis outbox that holds cluster events.
---

# A send held for the master is a durable operation — ADR

## Context

ADR-0145 decided that a person-facing send another computer asks of the master
waits while the master cannot be reached, "queued in the same outbox" as the
cluster events that computer produces offline, on its local Redis.

Two facts about such a send separate it from a held cluster event. A send has a
caller who must learn its outcome, a refusal by the master included, and every
outcome the platform reports after its request has returned is reported through
a durable operation with a receipt (ADR-0098). And a send waits for a live
master as well as for the cluster Redis, so it can wait while the cluster Redis
answers and cluster events flow; a single ordered outbox would hold every later
cluster event behind it.

An operation row already carries its work whole and survives a restart of the
daemon.

## Decision

A send that waits for the master is held as a durable operation on the
requesting computer. Its row carries the complete request, and its receipt
tells the caller that the message waits for the master. The operation stays
queued, across a restart of the daemon, until the master is reachable; it is
then carried, and the master's outcome is the operation's outcome. A held send
whose carrying had begun when the daemon stopped ends stale rather than being
carried again. The local Redis outbox holds cluster events only.

## Consequences

- One record holds each waiting send and its outcome, so there is no second
  store to keep consistent with the receipt.
- A held send's caller learns the outcome the way it learns every asynchronous
  outcome, and a daemon sending on its own behalf holds the same way with no
  caller to wake.
- The operation contract gains a held kind: a queued operation whose work waits
  for a condition is not marked stale by a restart.
- A send whose carrying was interrupted by a stop is reported stale instead of
  risking a second message to the person.

## Alternatives Considered

- **A send queue on the local Redis, beside the event outbox.** Rejected: the
  caller still needs an operation row for its outcome, so every held send would
  be written to two stores that must agree after any crash.
- **Sends in the event outbox itself, as ADR-0145 states.** Rejected: a send
  waiting for a live master would hold back every cluster event produced after
  it while the cluster Redis answers.
- **Answer "held" and report nothing later.** Rejected: a refusal by the master
  would never reach the caller, which the per-send failure contract forbids.
