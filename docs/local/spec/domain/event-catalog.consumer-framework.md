---
visibility: internal
description: Frozen v1 pointer to the executable event catalog — the attributes every platform event states about itself, the event type declarations producers construct and the catalog is generated from, the consumers that react to events, and the feature contracts that consume them.
---

# Event Catalog — Spec

## What it is

The v1 event catalog is generated from the event types producers construct; it
is not a second handwritten registry. Event attributes, type declarations, and
delivery behavior are read from the implementation and from the feature specs
that bind observable behavior.

## Canonical fields

- **Schema authority:** the event type declarations in `teleclaude/events/`,
  from which the catalog is generated.
- **Operator discovery:** `telec events list` and `telec events schema`.
- **Delivery implementation:** `teleclaude/events/`.
- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. No replacement event model is
  authored here.

### Envelope attributes

Every event on the platform event stream states facts about itself, and nothing
about its consumers
(`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`):

- **id:** the event's own identity. A producer that can emit one occurrence
  more than once states the same id each time, so consumers recognize the
  repeat.
- **type:** a dotted name whose first segment is the type's owner —
  `teleclaude` for what the platform itself emits, a published domain's name for
  that domain's events. An event relayed from an external system is named
  `<domain>.<name>` from what its declared source states.
- **source:** the emitting computer.
- **subject:** the one thing the event is about, as a typed reference.
- **time:** when it happened.
- **data:** the facts particular to the event's type.
- **home:** a registered project, person, or company, named in the
  configuration-subject vocabulary; none when the event belongs to no registered
  home; or unknown when the event does not carry it, because it predates these
  facts or reports an act whose record was kept before its home was. A project
  home also carries its owner as the emitting computer resolves it: the declared
  company or person, declared ownerless, or unresolved when that computer cannot
  read the project's ownership declaration. Unresolved is never reported as
  ownerless. Where `identity`'s reach reads an event, the event's home is the
  record's subject.
- **related:** typed references to the other things the event involves. When
  the event is produced while serving a request whose caller identity names a
  session, its related references include that session. Identity resolves the
  caller at the request boundary for the request's whole duration, whether the
  request is served directly or as a durable operation. Automation with no
  caller session references no session.
- **causationid:** the id of the event that caused this one, when one did.

A typed reference names a kind of thing and that thing's identity. The catalog
owns the set of kinds a reference can name and the shape of each kind's
identity; a producing context that needs a new kind adds it to that set.

The producer supplies the subject and the home: the envelope cannot be built
without them, and a home of none or unknown is stated explicitly. None is a
claim that the event belongs to no registered home; unknown makes no claim, and
a producer never states none or a guessed home in its place. The emission
boundary adds the source, time, session reference, and project owner, and an
id when the producer states none. Which
subject and home an event states, including for an event caused by earlier
events, is the producing context's emission invariant. Emission refuses and
alters nothing on the strength of these facts.

An event carries no notification rule, action affordance, audience, or routing
scope. Whether and how a consumer reacts is decided by that consumer from the
event's type, source, subject, and home; the data is opaque to routing.

Within one version of a type, the attributes and data evolve additively, and a
change that is not additive is a new version of the type. Event records the
platform keeps are migrated forward. Internal event bus envelopes are not
platform stream events; they state no subject and no home.

### Type declarations

Every event type is declared once, as the typed shape its producers construct,
and the catalog is generated from those declarations. A declaration states:

- the type's **name** and **version**, and a **description** of what happened;
- its **subject**: what its events are about, and the kind of thing their
  subject reference names;
- its **home**: the home kinds its events' home can take, or that they belong to
  no registered home;
- its **data fields**: each field's name, JSON value kind, and whether it may be
  null;
- its **related references**: the kinds of thing they name.

A producer can only emit an event its type's declaration allows. The catalog
owns the declaration's shape. The producing context authors its values, and the
events it emits carry attributes and data consistent with them.

### Event subjects and homes

The event platform's own emitters state as subject and home what their act
concerned:

- failure-burst and failure-cascade detection and processor worker crashes:
  the computer whose event processor observed them, with no home;
- a dead-lettered stream entry: the event it carried, with no home;
- entity degradation: the degraded thing the failing events it correlates are
  about, with the home of those events. Correlation keeps same-named things
  under different homes apart, so each degradation concerns one home. Failures
  with an unknown home are correlated together, and their degradation states an
  unknown home.
- signal ingest, clustering, and synthesis: the signal item, cluster, or
  synthesis the act produced, with no home while signal sources are machine
  configuration that no registered home declares.

### Discovery

The event list names every registered type; the schema view shows one type's
declaration in full
(`local/projects/teleclaude/spec/feature/event-catalog/event-discovery`). Both
read the generated catalog, so what an agent discovers is what producers emit.

### Consumption

Every reaction to platform events is a consumer with its own progress through
the stream on each computer
(`local/projects/teleclaude/spec/feature/event-catalog/event-consumers`):

- **Interest** is declared from event attributes only: type patterns, whether
  the consumer acts only on events its own computer emitted, and optionally the
  subject or home kinds it answers.
- **Type patterns** are an exact type name, a whole-segment prefix followed by
  `.*`, or `*`. The catalog owns this one matcher; every context that lets an
  author select events by type, such as procedure subscriptions and person
  notification preferences, validates and matches with it.
- **Duplicate protection** is the platform's: a consumer is handed an event
  once per event id while its record of the event is retained.
- **Retry and dead letter** are per consumer: bounded attempts, then the event
  is parked as that consumer's dead letter and announced, and the consumer
  continues.

The integration trigger, the lifecycle router, and correlation are consumers
that act only on events their own computer emitted. The notification path —
trust, deduplication, enrichment, classification, and the notification
projector — runs as the system pipeline.

### Ownership boundary

The catalog owns registry shape, discovery metadata, the reference kinds, the
envelope contract, the type-pattern matcher, and the consumer runtime: progress,
duplicate protection, retry, and dead letter. The bounded context that produces an event owns its
semantic name, data meaning, and emission invariant; consuming contexts own
their local reaction. Catalog registration does not transfer either
responsibility.

## Known caveats

- **Older computers read an earlier envelope.** Until no live computer reads
  it, every event also carries the earlier envelope's fields in the shape those
  computers read, under the fleet's interoperability contract
  (`local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`).
  The notification projector reads those fields and the notification rules
  kept beside the type declarations; no other consumer reads either.

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md
- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md
- docs/local/adr/0115-an-event-states-facts-and-its-consumers-own-every-reaction.md
- docs/local/adr/0116-each-reaction-to-a-platform-event-is-an-independent-consumer.md
- docs/local/spec/feature/event-catalog/event-envelope.md
- ~/.teleclaude/docs/sdlc/policy/domain-ownership.md — why hosting a context's event declarations confers no ownership of their meaning.
