---
visibility: internal
number: 0115
date: 2026-10-07
description: A platform event states only facts about what happened; notification rules, action affordances and routing scope leave the event and its catalog declaration, and each consumer decides its own reaction from the event's stated type, source, subject and home.
---

# An Event States Facts and Its Consumers Own Every Reaction — ADR

## Context

ADR-0105 held that a producer states facts about an event, never about its
consumers, and applied it to audience. Other consumer behavior still sat with
the producer:

- **Notification rules.** An event could carry a `human_action` intent, and its
  catalog declaration carried notification lifecycle rules: whether it creates,
  updates or resolves a notification, its grouping key and incident family,
  which fields are meaningful or silent, and whether it is actionable.
- **Action affordances.** An event could carry `actions` and resolution hints
  for whoever handled it.
- **Routing scope.** Each type declared a visibility, LOCAL or CLUSTER, read as
  which computers' consumers an event concerns. Every computer's event
  processor reads the same shared stream, so the declaration routed nothing; it
  was a filter each consumer had to remember to apply.

Each rule was written by a producer that cannot know who will consume its
event, and read by one consumer, the notification projector. Changing how
people are told about an event meant changing its producer.

## Decision

- **An event states what happened,** including the status it reports, and
  nothing about what anyone should do with it.
- **Notification rules and action affordances leave the event and its catalog
  declaration.** The consumer that tells people decides which events it tells,
  how it groups them and when an open matter is closed, from the event's
  stated facts and its own configuration.
- **Scope is not an event fact.** Whether a consumer acts on an event is its own
  filter over the stated type, source, subject and home. A consumer that acts
  only on its own computer's events filters on `source`.
- **Routing reads only those attributes.** The data is opaque until the consumer
  the event reaches reads it.

## Consequences

- A producer is written once, and new reactions to its events change no
  producer.
- Each consumer carries rules that producers used to carry. A consumer that
  tells people needs its own model of what opens and closes a matter.
- One routing vocabulary serves every consumer, and the filter a consumer
  applies is visible in that consumer rather than inferred from a producer's
  declaration.
- These fields are part of a shared shape. Under ADR-0026 they leave the wire
  only when no live node still reads them, so they outlive this decision until
  the notification projector that reads them is replaced on every computer.
- The in-process event bus keeps its own local-delivery distinction. It is a
  transport inside one process, not a fact on a platform event.

## Alternatives Considered

- **Keep the notification rules in the catalog but out of the envelope.**
  Rejected: the declaration belongs to the producing context, so the rule stays
  producer-owned and every change to how people are told still edits the
  producer's type.
- **Keep producer-declared scope as routing.** Rejected for the reason ADR-0105
  rejected a producer-declared audience: a producer cannot know which computers'
  consumers care, and the shared stream delivers every event to every computer
  regardless.
- **Let the payload carry routing hints.** Rejected: routing on payload couples
  every consumer to every producer's data shape.
