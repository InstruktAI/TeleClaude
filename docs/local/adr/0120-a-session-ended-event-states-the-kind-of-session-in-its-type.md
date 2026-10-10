---
visibility: internal
number: 0120
date: 2026-10-10
description: The session-ended event is emitted for every session that ends, and its type's last segment states what kind of session ended — a help-desk conversation, a person's own conversation, a session the platform or another session started, or unknown — read from who started the session, not from the principal it inherits.
---

# A Session-Ended Event States the Kind of Session in Its Type — ADR

## Context

A procedure subscribes to events by type pattern and answers one kind of home
(ADR-0110). A memory procedure that answers desk conversations in a project
home, subscribed to session ends, would be woken by every builder, reviewer
and orchestrator that ends in that project, and a worker the procedure itself
started would wake it again when that worker ended.

Routing reads only an event's attributes, never its data (ADR-0115), so a fact
in the data cannot keep those wakes away. The session-ended event was also
emitted only for sessions working in a project checkout, a condition taken
from its one consumer, so desk and personal-assistant conversations, which
work in company and person folders, were never reported at all.

What kind of session ended is a fact about the session, as its home is. A
session's principal does not state it: a session another session starts
carries its human's principal as lineage, so a worker and the conversation
that started it carry the same human principal.

## Decision

- **Every ending is reported.** A session-ended event is emitted for every
  session that ends, whatever folder it worked in, with the home it recorded;
  nothing about its consumers decides whether it is emitted.
- **The type states the kind.** The event's type ends in a segment naming what
  kind of session ended: a help-desk conversation, a person's own conversation,
  a session the platform or another session started, or unknown when the
  session's record establishes none of these. A pattern ending at the shared
  prefix selects every ending.
- **The kind is read from who started the session.** A session at a help desk
  is a help-desk conversation. A session the platform or another session
  started is a system session, whatever principal it inherited. A session a
  person started, with no session behind it, is that person's conversation. A
  record that establishes none of these is unknown, never guessed.

## Consequences

- A subscriber selects conversations by type pattern alone, and a procedure's
  own workers end as system sessions, so their ends never reach a procedure
  subscribed to conversations.
- A consumer that wants every ending selects the shared prefix; the lifecycle
  runner does, and keeps its own scope by acting only on endings in a project
  checkout.
- The earlier single type is retired, not renamed: one name cannot map to
  several, so events stored or emitted under it are not upcast to a kind, and
  a computer that predates the kinds keeps emitting the earlier name until it
  is upgraded.
- A new kind of session is a new type, which every subscriber that selects
  kinds individually must take up; a subscriber that selects the prefix takes
  it up unchanged.

## Alternatives Considered

- **One type, every subscriber woken by every ending.** Rejected: the procedure
  pays one agent turn for each irrelevant ending, its own workers re-trigger it,
  and project homes, where most workers run, are the noisiest.
- **The kind as a data field with data filters on subscriptions.** Rejected:
  routing reads attributes only (ADR-0115), and a data filter would make the
  subscription a second matching language beside the type pattern.
- **The kind read from the session's principal.** Rejected: a worker inherits
  its human's principal, so a principal-based kind would report every
  human-lineage worker as a person's conversation.
- **Emission scoped to the homes some consumer cares about.** Rejected: a
  producer cannot know its consumers, and the earlier checkout-only emission is
  exactly the defect this decision removes.
