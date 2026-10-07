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
- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. No replacement event model is
  authored here.

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
  configuration-subject vocabulary; none when the event concerns no registered
  home; or unknown when the event does not carry it, because it predates these
  facts or reports an act whose record was kept before its home was. A project

<!-- planned-change:personal-assistant-project-creation -->

subject also carries its owner as the emitting computer
resolves it: the declared company or person, declared ownerless, or
unresolved when that computer cannot read the project's ownership declaration.
<!-- change:personal-assistant-project-creation -->

subject also carries its owner as the emitting computer
resolves it under `local/projects/teleclaude/spec/feature/config/project-ownership`: a company or a person, ownerless, or
unresolved when that computer cannot resolve the project's ownership.
<!-- /planned-change:personal-assistant-project-creation -->

Unresolved is never reported as ownerless.

The producer supplies the subject: the envelope cannot be built without one,
and none and unknown must be stated explicitly. None is a claim that the event
concerns no registered home; unknown makes no claim, and a producer never states
none or a guessed home in its place. The emission boundary adds origin and
owner. Which subject an event states, including for an event derived from
earlier events, is the producing context's emission invariant. Emission refuses
and alters nothing on the strength of these facts.

The facts are additive envelope fields under the schema version. A reader treats
an event without them as having no session origin, no origin home, and an
unknown subject. Internal event bus envelopes are not platform stream events; they state
no subject.

### Type declarations

Every registered event type declares:

- its **subject assignment**: what its events are about, and the home kinds that
  subject can take, or none for a type whose events concern no registered home;
- its **payload fields**: each field's name and JSON value kind.

The catalog owns the declaration's shape. The producing context authors its
values, and the events it emits carry a subject and payload consistent with them.

### Event subjects

The event platform's own emitters state as their subject what their act
concerned:

- stream-health events (burst and failure-cascade detection, dead-lettered
  entries, processor worker crashes): no subject;
- entity degradation: the subject of the failing events it correlates.
  Correlation keeps same-named entities under different subjects apart, so each
  degradation concerns one subject. Failures with an unknown subject are
  correlated together, and their degradation states an unknown subject.
- signal ingest, clustering, and synthesis: no subject while signal sources are
  machine configuration that no registered home declares.

<!-- planned-change:retire-event-domains -->

The company business domains the platform hosts state their own subjects
(`local/projects/teleclaude/spec/domain/marketing`, `local/projects/teleclaude/spec/domain/creative_production`).
Hosting their handlers confers no ownership of their subjects.
<!-- change:retire-event-domains -->

The company business domains whose event vocabulary the catalog hosts state
their own subjects
(`local/projects/teleclaude/spec/domain/marketing`, `local/projects/teleclaude/spec/domain/creative_production`).
Hosting their vocabulary confers no ownership of their subjects.
<!-- /planned-change:retire-event-domains -->

### Discovery and visibility

- **Discovery views:** the event list names every registered type and tells
  its reader how an agent subscribes to a type; the schema view shows one
  type's metadata, subject assignment, and payload fields
  (`local/projects/teleclaude/spec/feature/event-catalog/event-discovery`).
  Both read the registry an agent's CLI validates a subscription request
  against, so what an agent discovers is what it may subscribe on.
- **Visibility:** an event's declared visibility names the computers whose
  consumers it concerns. A local event concerns only the computer that emitted
  it; a cluster or public event concerns every computer. Every computer reads
  the shared stream, so a consumer that acts per computer applies visibility
  where it receives the event.

### Ownership boundary

The catalog owns registry shape, discovery metadata, and delivery-envelope
contracts. The bounded context that produces an event owns its semantic name,
payload meaning, and emission invariant; consuming contexts own their local
reaction. Catalog registration does not transfer either responsibility.

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md
- docs/local/spec/feature/event-catalog/event-envelope.md

<!-- planned-change:retire-event-domains -->

- ~/.teleclaude/docs/sdlc/policy/domain-ownership.md — why hosting a domain's handlers confers no ownership of its event subjects.

<!-- change:retire-event-domains -->

- ~/.teleclaude/docs/sdlc/policy/domain-ownership.md — why hosting a domain's event vocabulary confers no ownership of its event subjects.

<!-- /planned-change:retire-event-domains -->
