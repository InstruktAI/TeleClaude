---
visibility: internal
description: Frozen v1 pointer to the executable event catalog and feature contracts that consume it.
---

# Event Catalog — Spec

## What it is

The v1 event catalog is executable source, not a second handwritten registry.
Event schemas, metadata, and delivery behavior are read from the implementation
and from the feature specs that bind observable behavior.

## Canonical fields

- **Schema authority:** `teleclaude/events/schemas/` and
  `teleclaude/events/catalog.py`.
- **Operator discovery:** `telec events list`.
- **Delivery implementation:** `teleclaude/events/`.
- **Maintenance stance:** see `project/spec/domain/glossary`. No replacement event model is
  authored here.

<!-- planned:event-origin-and-subject -->
### Envelope facts

Every event on the platform event stream states two facts about itself, and
nothing about its consumers:

- **Origin:** the emitting computer; when a verified caller session's request
  produced the event, that session and its recorded configuration subject as the
  origin home. Automation with no caller session states only the computer.
- **Subject:** a registered project, person, or company, named in the
  configuration-subject vocabulary, or none when the event is about the platform
  itself. A project subject also carries its owner — the declared company or
  person, or no owner — as the emitting computer resolves it. A project the
  emitting computer cannot resolve carries no owner.

The producer supplies the subject; the envelope cannot be built without one,
with none stated explicitly. The emission boundary adds origin and owner. An
event derived from one earlier event carries that event's subject. Emission
refuses and alters nothing on the strength of these facts.

The facts are additive envelope fields under the schema version. A reader treats
an event without them as having no session origin, no origin home, and no
subject. Internal event bus envelopes are not platform stream events; they state
no subject.

### Type declarations

Every registered event type declares:

- its **subject assignment**: what its events are about, and the home kinds that
  subject can take, or none for a type about the platform itself;
- its **payload fields**: each field's name and JSON value kind.

The catalog owns the declaration's shape. The producing context authors its
values, and the events it emits carry a subject and payload consistent with them.

<!-- /planned:event-origin-and-subject -->
### Ownership boundary

The catalog owns registry shape, discovery metadata, and delivery-envelope
contracts. The bounded context that produces an event owns its semantic name,
payload meaning, and emission invariant; consuming contexts own their local
reaction. Catalog registration does not transfer either responsibility.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
<!-- planned:event-origin-and-subject -->
- docs/project/adr/0105-event-access-follows-the-subject-its-producer-states.md
- docs/project/spec/feature/event-catalog/event-envelope.md
<!-- /planned:event-origin-and-subject -->
