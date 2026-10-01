---
visibility: internal
number: 98
date: 2026-09-22
description: Work that finishes after its response carries a durable operation row, distinct success and failure events, and delivery to the caller that asked for it.
---

# Async Work Always Carries a Receipt — ADR

## Context

Command classification offered three response modes. `IMMEDIATE` returns the
result in the response body. `RECEIPT` persists an operation row, returns a
receipt, and emits a completion event on the terminal transition.
`FIRE_AND_FORGET` sits between them: the work runs in the background, a `202`
names the event that will signal completion, and no durable record of the
outcome is kept anywhere.

Both async modes were introduced together, in the change that added
receipt-backed execution. The stated intent of that change was to replace
fire-and-forget patterns with pollable operations, yet the mode survived it and
two commands stayed on it.

Three consequences accumulated.

An outcome with no row cannot be asked about later. When the daemon dies
between a close request and its channel cleanup, the event is gone and the only
surviving evidence is residual session state, so a maintenance sweep infers the
unfinished work from a closed session that still carries a channel reference.
That sweep is the missing row, paid for in a worse currency.

The classification could not defend itself. Construction-time validation checked
one direction only — that a fire-and-forget command declares a completion event
— and nothing rejected the inverse. A command declaring itself `IMMEDIATE`
while running its work in a background task and emitting completion and failure
events afterwards constructed cleanly, shipped, and was absent from the
classification's own mapping table, so no reviewer comparing code to contract
could see the divergence.

Neither async mode reached an agent. A completion event was delivered to
WebSocket subscribers; an agent session is not one. Only the receipt path was
usable from an agent at all, and only because a command-line wrapper polled it
to a terminal state. An author reaching for the wrong mode got no error and no
signal.

The decision was contestable because a mode deliberately authored alongside its
alternative might be load-bearing: removing it could either close the drift or
force durability onto signals that legitimately have no interested reader.

## Decision

A command finishes before its response or after it. There is no third category.

Work that finishes after its response carries a durable operation row. The row
is written before execution begins and is the authority on what happened;
events are a nudge toward it, never the record itself.

Such a command declares two completion events, not one: success and failure as
distinct types. An outcome is read from the event's type, never inferred from a
payload field on a single shared type.

Caller provenance is a property of every command rather than of one command
class. At submission the acting caller is recorded on the operation row. On the
terminal transition, a recorded caller that is still live is woken with an
address — the operation's identity, its outcome, and where to read the full
record — never with the record's contents. A caller-less invocation writes its
row and wakes nobody; the record stands on its own.

Declaring completion events and being asynchronous are the same statement.
Validation enforces the biconditional at construction, so a command that runs
in the background cannot present itself as synchronous.

Work, row, and emission stay on the computer that owns the work. Only the
notification crosses a machine boundary, over the path that already carries
remote session outcomes to the session that dispatched them.

## Consequences

- Every async outcome survives a daemon restart and remains answerable
  afterwards, because a row exists to answer from.
- The maintenance sweep that reconstructs unfinished channel cleanup from
  residual session state has nothing left to reconstruct.
- Blocking poll helpers become a convenience for callers that genuinely want to
  wait, rather than the only channel through which an outcome is observable.
- Passive session subscription stops being the sole mechanism that returns an
  outcome to the agent that asked for one; the same delivery surface carries
  both.
- An async command executed on a remote computer requires the owning computer
  to accept a forwarded command and submit it to its own operations service.
  The dispatcher previously refused receipt-backed commands outright, so that
  refusal narrows to execution-in-transport rather than forwarding.
- Every async command now writes a row. The affected commands are rare and
  human- or agent-initiated, so the cost is negligible; a future high-frequency
  async command would need that cost weighed on its own evidence.
- Misclassification remains possible where a command's work is genuinely
  synchronous but slow. That is a correctness question about the command, which
  independent review catches, not a gap this contract can close.

## Alternatives Considered

- **Keep three modes and give fire-and-forget a delivery path.** Rejected
  because delivery without durability still loses every outcome whose recipient
  was absent or whose daemon restarted, leaving the compensating sweeps in
  place and the original failure unaddressed.
- **Keep the mode and add a durable row to it.** Rejected because a mode with a
  durable row, a terminal transition, and completion events is the receipt
  contract under a second name, and two names for one contract reproduce the
  drift that made this decision necessary.
- **Correct the misclassified command by awaiting its work inline.** Rejected
  because the work terminates an agent process, relaunches it, and waits for
  readiness under a timeout; holding a request open for that duration is what
  the receipt contract exists to avoid.
- **Record outcomes on a general event log rather than per-operation rows.**
  Rejected because the authority question is per-operation — what happened to
  this submission — and a consumer reading a shared log needs cursors and
  correlation to answer it, which is machinery this decision does not require.
