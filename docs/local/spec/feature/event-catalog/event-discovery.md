---
description: Agents discover which platform event types they can subscribe to, how
  to subscribe, and each type's declared subject assignment and payload fields from
  the event catalog's list and schema views.
---

# Event Discovery — Spec

## What it is

The event catalog shows agents what the platform emits. The event list names
every registered event type with its metadata and tells its reader how an agent
subscribes to a type. The schema view shows one type in full: its metadata, its
subject assignment, and every payload field the type declares with the field's
value kind. These are the fields a subscription may be narrowed on.

Both views read the same registry that an agent's subscription request is
validated against, so a type or field the views show is one an agent can
subscribe on, and one they do not show is refused
(`local/projects/teleclaude/spec/feature/agent_runtime/event-subscriptions`).
Declarations themselves are owned by the producing contexts and shaped by the
catalog (`local/projects/teleclaude/spec/domain/event-catalog`).

## Canonical fields

### Use cases

#### UC-ED1: The event list tells an agent how to subscribe

```gherkin
Given an agent reads the event list
When it looks for how to act on a listed event type
Then the list tells it how to subscribe to that event type
```

#### UC-ED2: An event type's schema shows what an agent can subscribe on

```gherkin
Given an agent wants to subscribe to a listed event type
When it views that event type's schema
Then it sees the type's metadata, its subject assignment, and every payload field the type declares with its value kind
```
