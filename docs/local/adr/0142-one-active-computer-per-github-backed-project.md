---
visibility: public
number: 142
date: 2026-10-27
description: A GitHub-backed project names its one active computer in a GitHub repository variable set only by a deliberate act; that computer alone starts the project's orchestrators and writes its claims, so no computer asks the master to admit a start.
---

# One Active Computer per GitHub-Backed Project — ADR

## Context

ADR-0135, ADR-0136 and ADR-0137 let a lifecycle orchestrator for a todo of a
project on the GitHub workflow store start on any computer that holds a
checkout, and make the fleet's master admit every start and write every claim.
GitHub has no conditional write, so a single decision point was the only way to
keep two computers from each finding a todo unclaimed and each starting an
orchestrator. That decision point puts the master on the path of every start:
while it is unreachable, no computer can start work on a GitHub-backed project,
and judging a claim means asking every computer about the claimed session.

Each computer already decides alone for a claimed item: it reads the session
the claim names and acts only when that session is its own. Only an item no
session claims has no computer to act for it. The project itself is where the
missing fact belongs, and GitHub offers a primitive for it: a repository
variable, a named value outside the committed tree that the App reads and
updates through the REST API.

## Decision

- **The project names its active computer.** A GitHub-backed project's active
  computer is the value of a repository variable on its repository. Every
  computer with a checkout reads it from GitHub.
- **Only a deliberate act changes it.** A command sets the variable; nothing
  sets it automatically. Because only a deliberate act writes it, the variable's
  last-writer-wins update is enough.
- **The active computer alone starts and claims.** Every orchestrator start for
  a todo of the project, and every claim write, happens on the active computer,
  in its own admission section (ADR-0133). No start is relayed to the master and
  the master admits nothing.
- **A claimed item is its session's.** A change to a claimed item is handled by
  the computer whose session the claim names, as now. A change to an item no
  session claims is handled by the active computer, and every other computer
  ignores it.
- **Working elsewhere means activating elsewhere.** To run the project's
  lifecycle on another computer, that computer is made active first.

## Consequences

- GitHub-backed work no longer depends on the master being reachable, and a
  claim is judged by the one computer that can write it, against its own
  sessions.
- The App needs the repository "Variables" permission on every GitHub-backed
  project.
- A start requested on a computer that is not active is refused with the
  computer that is, instead of being admitted remotely.
- Changing the active computer does not move a running orchestrator; its
  claimed item stays with its session's computer until that session ends.
- Projects on the default store are untouched: they live on one computer.

## Alternatives Considered

- **Master admission (ADR-0135 to ADR-0137).** Rejected: it serializes
  correctly but makes every start wait on the master and on asking every
  computer about a session.
- **A configuration field the master writes.** Rejected: every other computer
  would have to reach the master to read a fact that belongs to the project and
  that GitHub can hold.
- **A key in the cluster Redis.** Rejected: it adds a dependency for a fact the
  project's own repository can carry.
- **A board field, or a field in the ledger comment.** Rejected: a board exists
  only for organization repositories, and the ledger comment is the record whose
  missing conditional write caused the problem.
