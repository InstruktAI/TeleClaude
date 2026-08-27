---
description: The shape of a person's own data in their workspace, and how procedures consume it without naming individual documents.
---

# Person Knowledge — Spec

## What it is

A person's workspace holds what came out of their own interactions: who they
are to different correspondents, how they write, who matters, what they have
decided should always happen. Shared contracts never live here, and this data
never travels to another person.

Procedures reach it by **discovery, never by name**. Before work that involves
personal knowledge, an agent lists what the person's workspace publishes and
reads what it has not already loaded. No procedure names an individual
document, because the set grows as the person's assistant grows and a named list
is stale the day they add something.

## Canonical fields

The conventional contents. A person may hold more; nothing here is required for
the assistant to run, and an absent piece means the agent asks or proposes
rather than assumes.

- **Identity registry** — one entry per address the person sends from: the
  sphere of life it serves, its language, its register, and the rule for when
  fresh outbound should use it. This is what makes "reply from the right
  address" and "write in the right voice" answerable.
- **Standing instructions** — what the person has told the assistant to always
  or never do, recorded as it was given. Each exists once; a new instruction
  that contradicts an existing one is refused at recording time rather than
  stacked beside it.
- **Priorities** — who always matters, what is always noise, what the person
  wants surfaced rather than handled.
- **Examples** — real correspondence the person has approved as representative
  of their voice, kept as plain files outside the documentation taxonomy and
  referenced from here.

## Known caveats

- The workspace declares whose it is; identity is read from that declaration,
  never inferred from the folder's location.
- Everything here is personal data. It is never published to a shared surface,
  never quoted into another person's context, and never used to answer a
  question asked from outside that person's own work.
- A fact belongs in exactly one place. When the same thing appears in two
  documents, the duplicate is removed at the moment it is noticed during work
  that touches it — not by a periodic sweep.
