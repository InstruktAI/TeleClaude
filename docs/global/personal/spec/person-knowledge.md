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
document.

The listing is a directory listing. A person's knowledge lives in `knowledge/`
beneath their workspace root, one Markdown document per subject, and an agent
discovers it by listing that directory with ordinary file tools. It is not
reachable through `telec docs`, which resolves only global and project scopes;
a person's workspace is neither. Onboarding creates the directory and its first
documents, and every document a person accumulates afterwards joins it there.

## Canonical fields

The conventional contents. A person may hold more; nothing here is required for
the assistant to run, and an absent piece means the agent asks or proposes
rather than assumes.

- **Identity registry** — one entry per address the person sends from: the
  sphere of life it serves, its language, its register, and the rule for when
  fresh outbound should use it.
- **Standing instructions** — what the person has told the assistant to always
  or never do, recorded as it was given. Each exists once; a new instruction
  that contradicts an existing one is refused at recording time rather than
  stacked beside it.
- **Priorities** — who always matters, what is always noise, what the person
  wants surfaced rather than handled.
- **Examples of their voice** — a handful of messages per identity that the
  person has approved as representative, held in their workspace like the rest
  of their data. They carry the voice directly; no summary or description of how
  the person writes is held here.

  What an example is: **only what the person wrote** — no quoted thread beneath
  it, no auto-appended signature. Short and substantive beats long. Each carries
  one line saying which identity sent it and what kind of message it is — a
  client update, a decline, a piece of scheduling.

  The set is produced once, during onboarding, from the person's own sent mail.
  After that it changes only when they ask: telling an agent "more like this
  one" makes that message an example. When a new one covers a situation already
  represented, it replaces the weaker example rather than joining it.

## Known caveats

- The workspace declares whose it is; identity is read from that declaration,
  never inferred from the folder's location.
- Everything here is personal data. It is never published to a shared surface,
  never quoted into another person's context, and never used to answer a
  question asked from outside that person's own work.
- A fact belongs in exactly one place. When the same thing appears in two
  documents, the duplicate is removed at the moment it is noticed during work
  that touches it — not by a periodic sweep.
