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
- **Implementation roots:** `teleclaude/events/`.
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
- **source:** where the event originated: the emitting computer, and its
  **origin** there — a registered project, person, or company the act happened
  in, named in the configuration-subject vocabulary; none when the act happened
  in no registered project, person, or company; or unknown when the event does
  not carry it, because it predates these facts or reports an act whose record
  was kept before its origin was. A project origin also carries its owner as the
  emitting computer resolves it: the declared company or person, declared
  ownerless, or unresolved when that computer cannot read the project's
  ownership declaration. Unresolved is never reported as ownerless. Where
  `identity`'s reach reads an event, the event's origin is the record's subject.
- **subject:** the one thing the event is about, as a typed reference.
- **time:** when it happened.
- **data:** the facts particular to the event's type.
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

The producer supplies the subject and the origin: the envelope cannot be built
without them, and an origin of none or unknown is stated explicitly. None is a
claim that the act happened in no registered project, person, or company;
unknown makes no claim, and a producer never states none or a guessed origin in
its place. The emission
boundary adds the source, time, session reference, and project owner, and an
id when the producer states none. Which
subject and origin an event states, including for an event caused by earlier
events, is the producing context's emission invariant. Emission refuses and
alters nothing on the strength of these facts.

An event carries no notification rule, action affordance, audience, routing
scope, or home. Whether and how a consumer reacts is decided by that consumer
from the event's type, source and origin, and subject; the data is opaque to
routing. A consumer that works in a home — a project's checkout, a person's or
company's folder — resolves that home from the event's origin on its own
computer.

Within one version of a type, the attributes and data evolve additively, and a
change that is not additive is a new version of the type. Event records the
platform keeps are migrated forward. Internal event bus envelopes are not
platform stream events; they state no subject and no origin.

### Type declarations

Every event type is declared once, as the typed shape its producers construct,
and the catalog is generated from those declarations. A declaration states:

- the type's **name** and **version**, and a **description** of what happened;
- its **subject**: what its events are about, and the kind of thing their
  subject reference names;
- its **origin**: the kinds its events' origin can take, or that their acts
  happen in no registered project, person, or company;
- its **data fields**: each field's name, JSON value kind, and whether it may be
  null;
- its **related references**: the kinds of thing they name;
- its **state**, for a platform type that reports one: its family and the
  state, marked failing or ok.

A producer can only emit an event its type's declaration allows. The catalog
owns the declaration's shape. The producing context authors its values, and the
events it emits carry attributes and data consistent with them.

### Lifecycle states

A platform event that reports the state of a thing names that state in the last
segment of its type, under a family prefix shared by every state of that
lifecycle: a job's run outcomes, succeeded, failed and stalled, are three states
of one family.

- **The vocabulary is closed.** The catalog owns the set of state segments and
  marks each one failing or ok. A platform type whose last segment is in the
  vocabulary reports that state. A platform type that reports no state does not
  end in a state segment; an event about an act that leaves nothing to recover,
  such as a dead-lettered stream entry, reports no state.
- **Every failing family has a way back.** A family that declares a failing
  state also declares an ok state.
- **The subject is the thing whose state is reported.** Every state of a family
  has the same subject kind, and the thing is the subject within the event's
  origin, so a failure and its recovery state the same subject and origin.
- **The type alone carries the state.** A consumer reads a thing's state from
  the event's type, never from its data.
- **Declarations keep the convention.** The catalog is not generated from a
  declaration set that breaks these rules, so a producer cannot emit a state
  its family does not declare.

Events of published domains do not follow this convention; each domain names
its events as its own vocabulary requires.

### Event subjects and origins

The event platform's own emitters state as subject and origin what their act
concerned:

- failure-cascade detection and processor worker crashes: the computer whose
  event processor observed them, with no origin;
- failure-burst detection: the event type whose events burst, with the origin of
  those events; bursts of one type from different origins are kept apart;
- a dead-lettered stream entry: the event it carried, with no origin;
- entity degradation: the degraded thing the failing events it correlates are
  about, with the origin of those events. Correlation keeps same-named things
  from different origins apart, so each degradation concerns one origin.
  Failures with an unknown origin are correlated together, and their
  degradation states an unknown origin.
- signal ingest, clustering, and synthesis: the signal item, cluster, or
  synthesis the act produced, with no origin while signal sources are machine
  configuration that no registered project, person, or company declares.

Each detection reports when its episode is over: a burst and a failure cascade
subside, and a degraded thing recovers, once the events the detection counts no
longer reach its threshold within its window. A thing is degraded from the
first of its failing event types reaching the threshold until none does. An
episode that began before the computer's event processor restarted is still
reported over after the restart.

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
  subject kinds or origin kinds it answers.
- **Type patterns** are an exact type name, a whole-segment prefix followed by
  `.*`, or `*`. The catalog owns this one matcher; every context that lets an
  author select events by type pattern matches with it.
- **Duplicate protection** is the platform's: a consumer is handed an event
  once per event id while its record of the event is retained.
- **Retry and dead letter** are per consumer: bounded attempts, then the event
  is parked as that consumer's dead letter and announced, and the consumer
  continues.

The integration trigger, the lifecycle router, correlation, and the consumers
that tell people act only on events their own computer emitted. Every reaction
to a platform event is a consumer; no other pipeline processes the stream.

### Ownership boundary

The catalog owns registry shape, discovery metadata, the reference kinds, the
state vocabulary, the envelope contract, the type-pattern matcher, and the consumer runtime: progress,
duplicate protection, retry, and dead letter. The bounded context that produces an event owns its
semantic name, data meaning, and emission invariant; consuming contexts own
their local reaction. Catalog registration does not transfer either
responsibility.

### Governing designs and decisions

- `local/projects/teleclaude/design/architecture/event-delivery` — the one delivery model for domain events
- `local/projects/teleclaude/adr/0013-unified-cluster-events` — cluster-wide state propagation on one event namespace
- `local/projects/teleclaude/adr/0105-event-access-follows-the-subject-its-producer-states` — event access following the stated subject
- `local/projects/teleclaude/adr/0109-an-event-that-cannot-establish-its-subject-says-so` — an event that cannot establish its subject
- `local/projects/teleclaude/adr/0114-events-take-the-cloudevents-attribute-model` — the CloudEvents attribute model
- `local/projects/teleclaude/adr/0115-an-event-states-facts-and-its-consumers-own-every-reaction` — events stating facts while consumers own reactions
- `local/projects/teleclaude/adr/0116-each-reaction-to-a-platform-event-is-an-independent-consumer` — each reaction as an independent consumer
- `local/projects/teleclaude/adr/0117-a-platform-event-type-names-the-state-it-reports` — event types naming the state they report
- `local/projects/teleclaude/adr/0118-an-event-states-its-origin-and-a-home-is-a-consumers` — an event's origin and a consumer's home

## Known caveats

- **Older computers read an earlier envelope.** Until no live computer reads
  it, every event also carries the earlier envelope's fields in the shape those
  computers read, under the fleet's interoperability contract
  (`local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`).
  No consumer on a current computer reads them. The human action and routing
  scope among them are read only by an older computer's notification projector;
  they are carried until the fleet capability map shows every live computer
  carries incident alerts
  (`local/projects/teleclaude/spec/feature/integration/incident-alerts`), and
  from then on no event carries them.
- **The origin travels under a field named `home`.** The delivered model, wire
  form and declarations carry the origin's registered project, person, or
  company in a field named `home`. The name states nothing about any consumer's
  home; the field is the event's origin.

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md
- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md
- docs/local/adr/0115-an-event-states-facts-and-its-consumers-own-every-reaction.md
- docs/local/adr/0116-each-reaction-to-a-platform-event-is-an-independent-consumer.md
- docs/local/adr/0117-a-platform-event-type-names-the-state-it-reports.md
- docs/local/adr/0118-an-event-states-its-origin-and-a-home-is-a-consumers.md
- docs/local/spec/feature/event-catalog/event-envelope.md
- ~/.teleclaude/docs/sdlc/policy/domain-ownership.md — why hosting a context's event declarations confers no ownership of their meaning.
