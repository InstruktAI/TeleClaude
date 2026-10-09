---
visibility: internal
number: 0119
date: 2026-10-09
description: A receipt-backed CLI command returns its receipt without waiting, so every daemon-backed command ends either accepted or not accepted and the caller's wake is the only path an outcome takes back.
---

# The CLI Never Waits on a Receipt — ADR

## Context

ADR-0098 made every asynchronous command carry a durable operation row and wake
the caller recorded on it when the operation reaches a terminal state. It left
the command line's blocking poll helper in place as a convenience for callers
that want to wait.

The helper stayed on five commands: `telec todo prepare`, `work`, `integrate`,
`remove`, and the rename form of `update`. Each carried its own ceiling (30, 300
or 600 seconds), and none of these values was derived from what the operations
take. Over the week of operation records measured on 2026-10-09, `todo work`
never exceeded 114 seconds against its 600-second ceiling, while `todo integrate`
outran its 300-second ceiling 38 times. The agent runtimes also end a tool call
that runs past their own limit, so any ceiling above that limit could not be
reached.

Wakes were already being delivered: 621 operation outcomes reached their calling
session in one day. Every polled operation therefore reported its outcome twice,
inline from the poll and again through the wake.

The poll also blurred what a non-zero exit meant. A poll that met the daemon's
restart gap exited non-zero after the daemon had accepted the work. A caller
could not tell a command that was never accepted from one that was accepted and
lost track of, so no single instruction could tell it what to do next.

## Decision

The command line never waits on a receipt. A receipt-backed command prints the
receipt and returns. The outcome reaches the calling session through its wake,
and any reader, including a caller with no session to wake, reads the record
through the operation-status command.

Every daemon-backed command therefore ends in exactly one of two ways: accepted,
with its result or its receipt, or not accepted, with an error and nothing done.

## Consequences

- An orchestrator submits a state-machine step, yields, and reads the step's
  outcome when it is woken. Each step costs one more read than an inline result.
- A daemon restart no longer interrupts an accepted command at the command line.
  The restart marks the operation stale, and that terminal state wakes the caller.
- A non-zero exit always means not accepted, so guidance about what to do next
  can be attached to the failure itself.
- The per-command ceilings disappear, and with them the question of what value
  to give them.

## Alternatives Considered

- **Keep the per-command ceilings.** Rejected: the values were unmeasured, one was
  too short for the operation it bounded, and a poll outliving the runtime's
  tool limit is ended by the runtime rather than reported by the command.
- **One short wait for every receipt-backed command, returning the receipt when
  it expires.** Rejected: it keeps a second path to the same outcome and a
  second report of it, and a wait that meets a restart still blurs whether the
  command was accepted.
- **Poll through the restart gap.** Rejected: it adds retry machinery to a path
  the wake already covers, and the outcome it eventually reports is the stale
  state the wake delivers anyway.
