---
visibility: internal
number: 0117
date: 2026-10-08
description: A platform event that reports the state of a thing names that state in the last segment of its type, under a family prefix shared by every state of that lifecycle, from a closed failing/ok vocabulary the event catalog owns; every family that can report a failing state also declares an ok state.
---

# A Platform Event Type Names the State It Reports — ADR

## Context

ADR-0115 left the reaction to an event with its consumers and kept on the event
only what happened, including the status it reports. A consumer that tells
people about platform problems needs two facts from every event: which thing it
concerns, and whether that thing is now failing or working. ADR-0114 made the
subject the thing; nothing stated the state.

Platform types already read like states of a lifecycle — a job run succeeded,
failed or stalled — but only by naming habit. A consumer reading failure from
those names would be guessing, and three gaps followed from the habit:

- **Half a lifecycle.** Some failures had no reported way back: the correlation
  detections reported that a burst, a failure cascade or a degradation began,
  never that it was over.
- **The wrong thing.** A job outcome's subject was the single run, so a failure
  and the next run's success were about different things and never paired.
- **Selection by name.** Interests select events by type pattern. If failing
  and ok states lived under unrelated names, a pattern could select a failure
  and miss its recovery.

Routing reads only the event's attributes (ADR-0115), so the state has to be
readable without opening the data.

## Decision

- **The type names the state.** A platform event that reports the state of a
  thing names that state in the last segment of its type, under a family prefix
  shared by every state of that lifecycle.
- **The vocabulary is closed and owned by the event catalog.** Each state
  segment is marked failing or ok. A platform type that reports no state does
  not end in a state segment.
- **Every failing family has a way back.** A family that declares a failing
  state also declares an ok state.
- **The subject is the thing whose state is reported,** so every state of a
  family is about the same kind of thing, and a failure and its recovery are
  about the same thing.
- **The convention binds platform events only.** Published domains name their
  events as their own vocabulary requires.

## Consequences

- A consumer reads a thing's state from the event's type and subject alone,
  with no table of producers and no reading of the data, and a new producer
  that follows the convention takes part without changing any consumer.
- A type pattern that ends at a family selects every state of that lifecycle,
  so a consumer that wants the whole lifecycle can always select it.
- Producers carry more: a detection that reports an episode beginning must also
  report it ending, and keep enough state to do so across restarts.
- Some subjects widen from an occurrence to the thing it happened to — a job
  rather than a run — and the occurrence's identity moves into the data.
- Names are constrained: a platform event that reports no state must not end in
  a vocabulary word, and an event about a failed act that leaves nothing to
  recover is named as an occurrence, not as a state.
- The vocabulary changes only through the catalog. Adding a word is a catalog
  change that every consumer of states inherits.

## Alternatives Considered

- **A status fact in the event data or an extension attribute.** Rejected:
  routing reads only attributes, and failing and ok states under one type name
  would leave a type pattern unable to tell a lifecycle from a single fact.
- **One type per lifecycle with the state as a field.** Rejected: it breaks the
  existing past-tense naming of what happened, and a consumer selecting one
  state would still have to read the data.
- **Producer-declared alert actions, as alerting protocols do** (trigger and
  resolve with a deduplication key). Rejected: the producer would again state
  what a consumer should do, which ADR-0115 removed.
- **A per-consumer table mapping types to failing or ok.** Rejected: every new
  producer would require a change to every consumer that tells people.
- **Reading failure from words in type names.** Rejected: it guesses meaning
  from names, which drift as names change, and silently misses a lifecycle
  named differently.
