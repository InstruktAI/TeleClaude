---
visibility: public
number: 135
date: 2026-10-27
description: For a project on the GitHub workflow store, every lifecycle orchestrator start on any computer is admitted by the fleet's master, which records the claim before the session is created or claimed and judges an existing claim by asking the computers that could run its session; a claim stays held until they show it ended.
---

# GitHub-Backed Driver Starts Are Admitted by the Mesh Master — ADR

## Status

Superseded by ADR-0142

## Context

ADR-0133 and ADR-0134 make lifecycle orchestrator starts for one todo on one
computer pass the live-holder check and the creation or claim it admits one at
a time, in an in-process section that records nothing. That decides starts on
one computer only.

A project on the GitHub workflow store keeps its todos in its repository, and
every computer holding a checkout of the project reads and writes the same
items through its own working copy. The todo's claim, `active_runner`, holds a
session id, and every computer judges it against its own session registry. A
session running on another computer is absent from that registry, so the
lifecycle runner on a second computer treats the driving session as ended,
clears the claim and dispatches its own orchestrator. The runner autostarts by
default, and the platform's own project is checked out on every computer in
the fleet.

The record cannot decide between two computers. An item's record is a comment
that a write reads and then overwrites in separate requests, and GitHub offers
no conditional comment write, so two computers can both pass the revision check
before either writes. A computer that sleeps or loses its network keeps its
sessions while it drops out of the fleet's heartbeats, so a computer that does
not answer has not shown that its sessions ended.

The todo state and the item record reject fields they do not know, and a
computer on an older release can come back online after newer computers have
written. A change that adds a field to either breaks that computer's reading of
the item.

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
  is refused at once as busy (ADR-0134). Inside, it reads the item from GitHub,
  checks its own sessions, and judges the todo's claim.
- **The claim is recorded before the session exists.** When nothing holds the
  todo, the master records the claim — the session id and its origin marker —
  on the item before it answers, and the starting computer then refreshes its
  working copy and creates or claims the session. The claim keeps its shape;
  nothing else is recorded and nothing expires.
- **Each computer answers for its own sessions.** A computer keeps the record of
  every session it ran. For a claimed session id it answers that the session is
  its own and held — open there, or a start of it inside its admission section
  — that it is its own and ended, or that it is not its own.
- **A claim is held until its holder is shown to have ended.** The master asks
  every computer the platform knows, configured or discovered, about the
  claimed session. The answer of the computer that owns it decides; when every
  computer answers that it is not its own, the claim has ended; otherwise the
  claim is held. On any other computer, a claim naming a session it never ran
  is held and is never cleared there; the owning computer clears its own ended
  claims, and the master clears a claim it has judged ended when it admits the
  next start.
- **A start that finds the todo held is refused naming its holder.** The
  refusal names the holding session and the computer that answered for it, or,
  when no computer did, the computers that did not answer; the start creates
  and claims nothing. It is the driver-start conflict a start on one computer
  receives (ADR-0133).
- **A start that gives up after admission withdraws its claim.** When the
  starting computer cannot create or claim the session after asking, it
  refreshes its working copy and clears a claim still naming that session.
- **A start the master cannot decide creates nothing.** No live master, several
  computers declaring themselves master, a master that does not hold the
  project or runs a release without this decision, or a relay that does not
  answer refuses the start with that reason. No computer then decides the start
  by its own registry instead.
- **Local-store projects are unchanged.** Their starts are decided on their own
  computer as ADR-0133 and ADR-0134 state.

## Consequences

- At most one live orchestrator holds a todo of a GitHub-backed project among
  the computers running a release with this decision, through runner autostart
  and manual starts alike. A computer on an older release still judges claims
  by its own registry and can start a second one until it is updated.
- No todo or record shape changes, so a computer on any release reads every
  item as before.
- Starting an orchestrator for a GitHub-backed project depends on the master:
  while no master is live and reachable, starts on other computers are refused
  and runner passes skip those todos.
- Each start of a GitHub-backed todo costs a relay round trip, the master's read
  and write of the item and, when the todo is claimed, a question to each known
  computer, all inside the start's response window.
- A claim stays held while the computer running its session, or any computer
  when none answers for it, does not answer: a partitioned live driver is
  indistinguishable from an ended one.
- A start interrupted by its computer's restart after the master recorded its
  claim leaves the todo held from every computer's view until a later start of
  it is admitted, when every computer answers that the session is not its own.
- Admission requires the master to hold a checkout of the project.
- ADR-0035 is superseded in part: for a GitHub-backed project the master records
  the claim, and a claim naming a session a computer never ran is not stale
  there. ADR-0052 is superseded in part: across computers, the claim judged by
  the computers that could run its session decides whether a todo is held.
  ADR-0078 is superseded in part: a GitHub-backed claim is recorded before its
  session exists.

## Alternatives Considered

- **Check remote sessions without a single decision point.** Asking other
  computers, or reading the remote session snapshots in the daemon cache, stops
  a live remote driver from being cleared, but two computers that both find no
  claim still each start one.
- **Serialize through the item record.** The revision check and the record
  update are separate requests, and GitHub has no conditional comment write.
- **A cluster-bus lock with an expiry.** An expiry does not stop the former
  holder, so a late start or write survives the handover; ADR-0078 retired
  time-bound reservations for this reason.
- **Record the session's computer with the claim.** It would let the master ask
  one computer and name it when that computer is silent, but the todo state and
  the item record reject unknown fields, so a computer on an older release that
  returns after such a claim was written could not read the item.
- **Ask only the computers currently in the fleet's heartbeats.** A sleeping
  computer drops out of them while its driver lives, and its claim would be
  judged ended.
- **Take effect only once every live computer carries the decision.** Until then
  the new computers would decide starts by their own registry, the behaviour
  this decision removes; refusing instead needs no agreement, because no shared
  shape changes.
- **The per-project work-control claim of the GitHub work-control design.** It
  names one computer per project from the ledger's comment order, but it is not
  yet delivered, it governs issue handling rather than starts, and it lets an
  operator release an offline holder, which reopens the overlap this decision
  excludes.
- **Run every orchestrator of a GitHub-backed project on one computer.** It
  serializes as well, but moves where sessions run and ends in-place starts on
  every other computer.
