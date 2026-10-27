---
visibility: public
number: 136
date: 2026-10-27
description: For a project on the GitHub workflow store, every write that sets or clears a todo's claim is made by the fleet's master inside its admission section for that todo; other computers ask it to release, and its lifecycle runner passes clear claims it judges ended.
---

# Only the Master Writes a GitHub-Backed Claim — ADR

## Context

ADR-0135 makes the fleet's master admit every orchestrator start of a todo in a
project on the GitHub workflow store and record the claim before the session
exists. It leaves clearing a claim to the computer whose session ended — at
session end, in startup housekeeping and in lazy runner reconciliation — and to
the master when it admits the next start.

An item's record is overwritten in two requests, a read and a write, with no
conditional write between them. The moment a session ends is the moment its
computer clears the claim and also the moment the master, asked about that
session, hears that it has ended and records a new claim. A clear that reads
the record before the master's write and writes after it erases the new claim.
With the claim gone, the master's next admission finds nothing holding the todo
and admits a second orchestrator beside the live one.

A start that stops waiting for its admission can also leave a claim the master
records after the start has given up, for a session that is never created. If
only a later admitted start clears such a claim, a todo nobody drives stays
held from every lifecycle runner's view.

## Decision

- **One writer while a todo can be started.** For a todo in a project on the
  GitHub store that a lifecycle orchestrator can still be started for, every
  write that sets or clears its claim is made by the master, inside its
  admission section for that todo, against the item it has just read from
  GitHub. No other computer writes that claim.
- **Other computers ask the master to release.** When a computer would clear a
  claim for a session it ran — the session ended, its housekeeping finds it
  ended, its caller releases it, or a start it made gave up after asking for
  admission — it asks the master to release the claim naming that session. The
  master clears it only while the claim still names that session. A request
  that does not reach the master leaves the claim for the master's own
  reconciliation.
- **The master reconciles in its runner passes.** In each lifecycle runner pass
  for such a project, the master judges every claim for a session it does not
  hold as ADR-0135 states, inside its section for the todo, and clears the
  claims it judges ended. A todo whose section is busy is left for the next
  pass.
- **Clears the master makes stay as before.** The master clears a claim for its
  own ended session the same way, inside its section.
- **Delivery and removal keep their own clears.** Delivering or removing a todo
  clears its claim as part of that transition, as before. No orchestrator start
  is admitted for a delivered or removed todo, and removal is refused while a
  live session holds the todo, so such a clear cannot erase a claim the master
  recorded for a new start.

## Consequences

- No write erases a claim the master recorded after judging the previous one
  ended, because every claim write for the todo is ordered by the master's
  section and made against what GitHub holds.
- A todo whose driver ended on another computer is free once that computer's
  release reaches the master, or by the master's next runner pass after it.
- A claim the master recorded for a start that had already given up is cleared
  by its next runner pass, once every computer answers that the session is not
  its own.
- Releasing a claim costs a relay round trip from a computer other than the
  master; while the master is unreachable, ended claims stay held.
- ADR-0135 is superseded in part: computers other than the master no longer
  clear a GitHub-backed claim themselves, and the master also clears ended
  claims in its runner passes.

## Alternatives Considered

- **Let each computer clear its own ended claims (ADR-0135).** The clear races
  the master's write of the next claim at the moment the session ends.
- **Answer "held" while a computer's own clear is in flight.** It closes the
  race only for clears that one process knows about; startup housekeeping and
  a restart between answering and clearing reopen it.
- **Clear dangling claims only when the next start is admitted.** The lifecycle
  runners treat the todo as driven and never start it, so the todo waits for a
  manual start.
