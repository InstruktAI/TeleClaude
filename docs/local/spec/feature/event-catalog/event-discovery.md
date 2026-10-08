---
description: Agents discover which platform event types are registered and each
  type's declared subject assignment and payload fields from the event catalog's
  list and schema views.
---

# Event Discovery — Spec

## What it is

The event catalog shows agents what the platform emits. The event list names
every registered event type with its metadata and points its reader to the
schema view. The schema view shows one type in full: its metadata, its subject
assignment, and every payload field the type declares with the field's value
kind.

Both views read the catalog's registry. Declarations themselves are owned by the
producing contexts and shaped by the catalog
(`local/projects/teleclaude/spec/domain/event-catalog`).

## Canonical fields

### Use cases

#### UC-ED1

#### UC-ED2: An event type's schema shows what its events carry

```gherkin
Given an agent wants to know what a listed event type carries
When it views that event type's schema
Then it sees the type's metadata, its subject assignment, and every payload field the type declares with its value kind
```
