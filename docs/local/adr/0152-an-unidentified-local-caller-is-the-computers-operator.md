---
visibility: public
number: 152
date: 2026-10-30
description: A caller on a computer for which no session, terminal login or carried identity resolves acts as the computer's operator under the system principal system:operator, instead of being refused or registered as a customer.
---

# An Unidentified Local Caller Is the Computer's Operator — ADR

## Context

On a computer with more than one registered person, a local caller that no
session record, terminal login or TUI-carried identity identifies is refused by
the command line, and an agent the platform did not launch is registered as a
customer, which session creation then refuses outside a help desk. Agents started
by another local application — an editor, a desktop agent host, a scheduler —
have no terminal anywhere in their process ancestry, so they can never log in:
the platform's documentation, reminders, todos and commits stay closed to them.

Every such caller runs as the operating-system user the installation runs as.
That user already holds every authority the platform has on the computer: it can
run the lifecycle targets, read every store, and write to the daemon's socket
directly. The identity specification already records that the daemon's request
surface is not an isolation boundary between local processes. A refusal here
therefore protects nothing and blocks the one caller that holds full authority.

## Decision

A local caller for which nothing resolves an identity is the computer's operator.
It carries the system principal `system:operator`, is cleared as the operator for
every command, and its headless session is created under that principal with no
person role. The principal names no person: the operator's work is attributed to
no human, no person-bound service acts for it, and no person's conversation
memory is drawn from its sessions. A session identity document that names no
admissible session is not the operator and stays refused, and a person's own
login, session or carried identity keeps answering exactly as before.

## Consequences

- Agents started outside the platform's launch flow use the full `telec`
  surface without a login, and their sessions become observable records.
- Requests the operator addresses to another computer carry `system:operator`
  and are admitted there as a system caller, the trust the computers' daemons
  already extend to each other.
- Records the operator creates carry `system:operator` as their lineage root, so
  attribution to a person needs the person's own identity, not account lineage.
- A computer whose operating-system account is shared with people who should not
  hold platform authority has no protection from this boundary; such an
  installation needs a separate operating-system user per person.

## Alternatives Considered

- **Keep refusing.** Rejected: it protects no asset the operating-system user
  cannot already reach, and it leaves every externally started agent unusable.
- **Resolve to the sole platform administrator.** Rejected: it attributes
  unidentified work to a named human, the misattribution the retired
  machine-global login record produced.
- **A synthetic email such as `operator@system.local`.** Rejected: an email
  outside the people registry resolves as an unknown human, which the platform
  reduces to the customer role, and it would surface as a person wherever
  people are listed.
