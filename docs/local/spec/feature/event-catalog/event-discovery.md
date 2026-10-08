---
description: Agents discover which platform event types are declared and each
  type's declaration — what its events are about, their origin, their data fields
  and their related references — from the event catalog's list and schema views.
---

# Event Discovery — Spec

## What it is

The event catalog shows agents what the platform emits. The event list names
every declared event type with its version and what its events are about, and
points its reader to the schema view. The schema view shows one type's
declaration in full: its name, version and description, what its events are
about and the kind of their subject, the kinds their origin can take or that
their acts happen in no registered project, person or company, every data field with its value kind and whether it may
be null, the kinds of thing their related references name, and, for a platform
type that reports a state, its family and whether the state is failing or ok.

Both views read the catalog generated from the event types producers construct,
so what an agent discovers is what producers emit. A type's first name segment
names its owner, and the list can be narrowed to one owner. The views show no
notification rule, action, audience or routing scope, because an event type
declares none (`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`).
Declarations themselves are owned by the producing contexts and shaped by the
catalog (`local/projects/teleclaude/spec/domain/event-catalog`).

## Canonical fields

### Use cases

#### UC-ED1

#### UC-ED2: An event type's schema shows what its events carry

```gherkin
Given an agent wants to know what a listed event type carries
When it views that event type's schema
Then it sees the type's name, version and description, what its events are about and the kind of their subject, the kinds their origin can take or that their acts happen in no registered project, person or company, every data field with its value kind and nullability, and the kinds of thing their related references name
And for a platform type that reports a state, it sees the type's family and whether the state is failing or ok
And it sees no notification rule, action, audience or routing scope
```

#### UC-ED3: The event list narrows to one owner

```gherkin
Given an agent wants the event types one owner emits, such as the platform itself or a published domain
When it lists the event catalog narrowed to that owner
Then it sees exactly the declared types whose name begins with that owner's segment
```
