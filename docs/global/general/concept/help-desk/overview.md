---
description: A help desk is the folder in a home where an agent answers people that
  home does not otherwise serve — the three kinds, how a conversation reaches one,
  what its agent may read, and where escalation goes.
visibility: public
---

# Help Desk — Concept

## What

A help desk is a folder inside a home where an agent answers questions from
people the home does not otherwise serve. A home runs one only when its
configuration enables it, and the folder's location follows from the home.
Desks run only on the platform's master computer, which hosts every enabled
desk. There are two kinds, each described in its own concept:

- **Company desk** (`general/concept/help-desk/company`) — a company's desk for
  its external customers.
- **Project desk** (`general/concept/help-desk/project`) — a project's desk for
  its external customers. The TeleClaude project's desk is a project desk like
  any other.

A desk is one kind of endpoint a conversation can reach; a person's own
assistant is the other. A person reaches a desk through its entry link, which
carries the desk's entry identifier: its kind and slug, and nothing else.
Entering a desk continues that person's latest session there: an open session
carries on, a closed one is revived, and a person with no session there gets a
new one. That session becomes the conversation's session, so the latest entry
decides where a conversation goes. A message without an identifier goes to the
conversation's session and revives it when it was closed. A registered person
whose conversation has no session reaches their own assistant.

An identifier that names no existing or enabled desk, and a message without an
identifier from a person who is not registered and whose conversation has no
session, receive one fixed neutral reply and no session. The reply is the same
in every case and names no organisation. No other route exists: a person is
never sent somewhere by their role or by where they were before.

A desk agent reads documentation at the depth its visitor holds. A customer
holds no relationship to the home, so the agent reads that desk's public
documentation and the public help-desk documentation.

When the agent cannot help, it escalates. Everyone in the desk's scope is
notified: the members and admins of the company the desk belongs to, the person
who owns a person-owned project, and the platform's admins. The escalation
opens a thread named after the visitor in the desk's own escalations channel,
and whoever answers there reaches the visitor on the channel they wrote from,
until they hand the conversation back to the agent.

## Why

- A home's customers need the answers the home already published, without an
  account and without reaching anything the home did not publish.
- Naming a desk by kind and slug keeps entry deterministic: a link reaches an
  enabled desk or gets the neutral reply, never a guess.

- Letting the latest entry decide gives every person one simple rule on every
  channel: they are where they last chose to go.
- Continuing a person's own session at a desk keeps their conversation whole
  across absences; closing a session only spares resources while they are away.
- Routing only by what a person sent keeps every outcome explainable: nobody is
  placed by a guess about their role or their past.
- One computer hosting every desk gives each desk exactly one host: a desk
  declared in a repository checked out on several computers never competes
  with itself.

- A reply that is identical for every miss and names no organisation tells a
  stranger nothing about who the platform serves.

- Escalation reaches everyone accountable for the desk, in the desk's own
  channel, not whoever happens to watch a shared one.
