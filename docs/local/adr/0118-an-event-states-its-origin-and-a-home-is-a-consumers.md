---
visibility: internal
number: 0118
date: 2026-10-08
description: The registered project, person or company an act happened in is part of the event's origin, stated with its emitting computer as its source; an event states no home, because a home is where a consumer works and only a consumer resolves it, on its own computer, from the event's origin.
---

# An Event States Its Origin, and a Home Is a Consumer's — ADR

## Context

ADR-0105 gave every event a fact naming the registered project, person or
company its act concerned, and called it the subject. ADR-0114 moved that fact
out of `subject` into an extension named `home`, described as "the home the
event belongs to", on which "reach and procedure homes key".

A home, in this platform's vocabulary, is the registered folder where work
happens: a project's checkout, a person's or company's folder. Whether an event
leads to work in a home, and in which, is a decision only a consumer can make,
on its own computer, from what it knows is registered there. Describing an event
as having or belonging to a home stated a consumer's resolution as a fact about
the event, and defined the event's attribute by the consumers that read it.
Every contract derived from ADR-0114 then repeated that framing: events
"belonging to" homes, reach that "follows the home", standing agents working
"in the home the event states".

The fact itself was never wrong. It records where the act happened, which is
part of the event's origin, beside the computer that emitted it.

## Decision

- **The project, person or company an act happened in is the event's origin.**
  With the emitting computer it forms the event's source: where the event
  originated. It keeps its three values — a registered project, person or
  company, none, or unknown — and a project origin keeps its owner as resolved
  on the emitting computer.
- **An event states no home.** No contract describes an event as having,
  belonging to, naming or choosing a home.
- **A home is a consumer's.** A consumer that works in a home resolves it from
  the event's origin on its own computer, and owns that resolution. A consumer
  may declare the kind of home it works in; it is activated by events whose
  origin is of that kind.
- **Reach reads the origin.** Where receiving-side reach decides who may see an
  event, the event's origin is the record's subject.
- **The delivered field keeps its name.** The model, wire form and declarations
  delivered under ADR-0114 carry the origin in a field named `home`. The field
  is the event's origin; its name states nothing about any consumer's home.

## Consequences

- The event contract states only facts about the event: what happened, the
  thing it is about, and where it originated. Consumer vocabulary appears only
  in consumer contracts.
- Every contract that read the fact as the event's home reads it as the event's
  origin, with no change in behavior.
- A field named `home` that carries the origin stays a known mismatch between the
  wire name and the contract term until a shared-shape change renames it under
  ADR-0026.

## Alternatives Considered

- **Keep the `home` wording.** Rejected: it states a consumer's resolution as an
  event fact, which is the coupling the event platform exists to remove.
- **Rename the field in the same decision.** Rejected: the field is a shared
  shape across a mixed-version fleet, so renaming it is a change with its own
  cost under ADR-0026, and the contract is corrected without it.
