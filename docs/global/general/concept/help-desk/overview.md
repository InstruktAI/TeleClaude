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
There are three kinds, each described in its own concept:

- **Platform desk** (`general/concept/help-desk/platform`) — the TeleClaude
  home's desk for internal users who have no personal assistant.
- **Company desk** (`general/concept/help-desk/company`) — a company's desk for
  its external customers.
- **Project desk** (`general/concept/help-desk/project`) — a project's desk for
  its external customers.

A desk is one kind of endpoint a conversation can reach; a person's own
assistant is the other. A customer reaches a company or project desk through
that desk's entry link, which carries the desk's entry identifier: its kind and
slug, and nothing else. Entering creates a session at the desk, and the
conversation's next messages go to its latest session, so the latest entry
decides where a conversation goes. A returning customer lands at the desk they
last used. A registered person who follows a desk link is served by that desk
until they use their own assistant's link again. The platform desk has no entry
identifier: its visitors reach it by the role they hold.

A conversation that names no desk, names one that does not exist, or names one
that is not enabled receives one fixed neutral reply and no session. The reply
is the same in all three cases and names no organisation.

A desk agent reads documentation at the depth its visitor holds. A customer
holds no relationship to the home, so the agent reads that desk's public
documentation and the public help-desk documentation.

When the agent cannot help, it escalates. The admins of the home that owns the
desk are notified with the desk and the visitor, and an admin's answers reach
the visitor on the channel they wrote from until the admin hands the
conversation back to the agent.

## Why

- A home's customers need the answers the home already published, without an
  account and without reaching anything the home did not publish.
- Naming a desk by kind and slug keeps entry deterministic: a link reaches an
  enabled desk or gets the neutral reply, never a guess.
- Letting the latest entry decide gives every person one simple rule on every
  channel: they are where they last chose to go.
- A reply that is identical for every miss and names no organisation tells a
  stranger nothing about who the platform serves.
- Escalation reaches the people accountable for the home the visitor came to,
  not whoever happens to watch a shared channel.
