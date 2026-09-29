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

- **Origin:** the emitting computer. When the event is produced while serving a
  request whose caller identity names a session, origin also includes that
  session and its recorded configuration subject as the origin home. Identity
  resolves the caller at the request boundary for the request's whole duration,
  whether the request is served directly or as a durable operation. Automation
  with no caller session states only the computer.
- **Subject:** a registered project, person, or company, named in the
  configuration-subject vocabulary, or none when the event is about the platform
  itself. A project subject also carries its owner as the emitting computer
  resolves it: the declared company or person, declared ownerless, or
  unresolved when that computer cannot read the project's ownership declaration.
  Unresolved is never reported as ownerless.

The producer supplies the subject: the envelope cannot be built without one,
and none must be stated explicitly. The emission boundary adds origin and
owner. Which subject an event states, including for an event derived from
earlier events, is the producing context's emission invariant. Emission refuses
and alters nothing on the strength of these facts.

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

### Event subjects

The event platform's own emitters state as their subject what their act
concerned:

- stream-health events (burst and failure-cascade detection, dead-lettered
  entries, processor worker crashes): no subject, because they concern the
  stream, whatever events they count;
- entity degradation: the subject of the failing events it correlates.
  Correlation keeps same-named entities under different subjects apart, so each
  degradation concerns one subject.
- signal ingest, clustering, and synthesis: no subject while signal sources are
  machine configuration that no registered home declares;
- the company business domains the platform hosts (marketing, creative
  production, customer relations): the company whose business the event
  records. A feed event bridged from a signal event carries that signal event's
  subject.

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
