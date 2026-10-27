---
visibility: public
number: 135
date: 2026-10-27
description: For a project on the GitHub workflow store, every lifecycle orchestrator start on any computer is admitted by the fleet's master, which records the claim naming the session and its computer before the session is created or claimed; only the computer a claim names judges whether it has ended.
---

# GitHub-Backed Driver Starts Are Admitted by the Mesh Master — ADR

## Context

ADR-0133 and ADR-0134 make lifecycle orchestrator starts for one todo on one
computer pass the live-holder check and the creation or claim it admits one at
a time, in an in-process section that records nothing. That decides starts on
one computer only.

A project on the GitHub workflow store keeps its todos in its repository, and
every computer holding a checkout of the project reads and writes the same
items through its own working copy. The todo's claim, `active_runner`, holds
only a session id, and every computer judges it against its own session
registry. A session running on another computer is absent from that registry,
so the lifecycle runner on a second computer treats the driving session as
ended, clears the claim and dispatches its own orchestrator. The runner
autostarts by default, and the platform's own project is checked out on every
computer in the fleet.

The record cannot decide between two computers. An item's record is a comment
that a write reads and then overwrites in separate requests, and GitHub offers
no conditional comment write, so two computers can both pass the revision check
before either writes. Excluding a second driver across computers therefore
needs one place that decides every start of a todo, a claim that says which
computer's registry can confirm its session, and a rule for a computer that
does not answer.

The platform already routes a decision that must be made once for the whole
fleet to one computer: a person-addressed message is carried over the
computer-addressed relay to the fleet's unique live master, which acts and
returns its outcome to the requesting computer.

## Decision

- **The master admits.** For a project on the GitHub store, every start that
  would make a session a todo's lifecycle orchestrator — a session create door
  launching an orchestrator role, or a `telec todo prepare` or `telec todo work`
  operation claiming the todo for its caller — is admitted by the fleet's
  master before the session is created or the caller claimed. A start on
  another computer carries its admission request to the master over the
  computer-addressed relay; a start on the master decides it in process. Task
  lanes are not repository work and are not admitted this way.
- **The starting computer holds its section across the admission.** The start
  enters its own computer's admission section for the todo (ADR-0133) before it
  asks, and leaves it only after it has created or claimed the session, or
  given up. While it is inside, that session counts on its computer as starting.
- **The master decides one start of a todo at a time.** It takes its own
  admission section for the project and todo, so its local starts and every
  relayed admission for the todo share one decision point; a colliding request
  is refused at once as busy (ADR-0134). Inside, it reads the item from
  GitHub, checks its own sessions, and checks the claim. A claim naming the
  master is judged against its own registry; a claim naming another computer
  is judged by asking that computer. A computer that does not answer leaves the
  claim held.
- **A start that finds the todo held is refused naming its holder.** The
  refusal names the holding session and the computer it runs on, and says so
  when that computer did not answer; the start creates and claims nothing. The
  refusal is the same driver-start conflict a start on one computer receives
  (ADR-0133), now carrying the holder's computer.
- **The claim names its computer and is recorded before the session exists.**
  When nothing holds the todo, the master records the claim — the session id,
  the computer the relay names as the start's source, and its origin marker —
  on the item before it answers. The starting computer then refreshes its
  working copy and creates or claims the session. The claim is the one
  ownership fact; nothing else is recorded and nothing expires.
- **Only the computer a claim names ends it.** A computer judges a claim naming
  itself: it is held while a session with that id is open there or a start of
  that session is inside its admission section, and ended otherwise. Every other
  computer treats a claim naming another computer as held and never clears it.
  The named computer clears it when the session ends, or when its lazy
  reconciliation finds it ended; the master clears it when that computer
  answers that it has ended.
- **A start the master cannot decide creates nothing.** No live master, several
  computers declaring themselves master, a master that does not hold the
  project, or a relay that does not answer refuses the start with that reason.
- **Local-store projects are unchanged.** Their starts are decided on their own
  computer as ADR-0133 and ADR-0134 state.
- **It takes effect when the fleet agrees.** Cross-computer admission is a
  capability every computer must share, marked as one that must be negotiated
  (ADR-0027). While any live computer does not carry it, starts are decided on
  each computer as ADR-0133 and ADR-0134 state and no claim names a computer, so
  an older release never reads a claim shape it does not know.

## Consequences

- Once every live computer carries the capability, at most one live
  orchestrator holds a todo of a GitHub-backed project across the fleet, through
  runner autostart and manual starts alike. Before that, two computers can still
  each start one, as before this decision.
- A computer on an older release that comes online after claims naming a
  computer were recorded cannot read those items until it is updated.
- Starting an orchestrator for a GitHub-backed project depends on the master:
  while no master is live and reachable, starts on other computers are refused
  and runner passes skip those todos.
- Each start of a GitHub-backed todo costs a relay round trip, the master's read
  and write of the item, and the starting computer's refresh, all inside the
  start's response window.
- A claim naming a computer that never answers again stays held: no other
  computer can establish that its session ended, and a partitioned live driver
  is indistinguishable from an ended one.
- A claim recorded for a start that never created its session costs nothing
  lasting: its computer reports it ended once that start has left its section,
  and the next admission or that computer's reconciliation clears it.
- Admission requires the master to hold a checkout of the project.
- Claims recorded before this decision name no computer and are judged as
  before, by each computer's own registry.
- ADR-0035 is superseded in part: a claim names its session's computer, the
  master records it for a GitHub-backed project, and only that computer clears
  it as stale. ADR-0052 is superseded in part: across computers, the claim
  verified by the computer it names decides whether a todo is held. ADR-0078 is
  superseded in part: a GitHub-backed claim is recorded before its session
  exists.

## Alternatives Considered

- **Check remote sessions without a single decision point.** Asking the claim's
  computer, or reading the remote session snapshots in the daemon cache, stops a
  live remote driver from being cleared, but two computers that both find no
  claim still each start one.
- **Serialize through the item record.** The revision check and the record
  update are separate requests, and GitHub has no conditional comment write.
- **A cluster-bus lock with an expiry.** An expiry does not stop the former
  holder, so a late start or write survives the handover; ADR-0078 retired
  time-bound reservations for this reason.
- **The per-project work-control claim of the GitHub work-control design.** It
  names one computer per project from the ledger's comment order, but it is not
  yet delivered, it governs issue handling rather than starts, and it lets an
  operator release an offline holder, which reopens the overlap this decision
  excludes.
- **Run every orchestrator of a GitHub-backed project on one computer.** It
  serializes as well, but moves where sessions run and ends in-place starts on
  every other computer.
- **Let the claim's computer decide, and the master only unclaimed todos.** Two
  authorities would each decide some starts of one todo, and a claim cleared on
  its computer while the master admits another start would race.
