---
description: Every platform event states, in one typed shape, what happened, where it originated, the one thing it is about, and what else it involves; it states facts about itself only, never about its consumers, and each event type's declaration, from which the catalog is generated, says which of those facts its events carry.
visibility: internal
---

# Event Envelope — Spec

## What it is

Every event on the platform event stream describes itself with a small set of
attributes, set by its producer where the event happens:

- **id** — the event's own identity. A producer that can emit one occurrence
  more than once states the same id each time. Distinct occurrences never
  share an id, so consumers distinguish a replay from a new event
  (`local/projects/teleclaude/spec/feature/event-catalog/event-consumers`).
- **type** — what happened, as a dotted name whose first segment says who owns
  the type: `teleclaude` for what the platform itself emits, or the name of a
  published domain, such as `sdlc`, for that domain's events. An event from an
  external system enters through an inbound endpoint as an event of the domain
  its source declares.
- **source** — where the event originated: the computer it was emitted on, and
  its **origin** there, the registered project, person or company the act
  happened in; none when the act happened in no registered project, person or
  company, such as an event about the platform itself; or unknown when the
  producer cannot establish it. A project origin also carries its owner as
  resolved on the emitting computer: the owning company or person, no owner, or
  unresolved when that computer cannot read the project's ownership.
- **subject** — the one thing the event is about, as a typed reference: the kind
  of thing and its identity, such as a todo, a session, a job or a computer.
- **time** — when it happened.
- **data** — the facts particular to the event's type.
- **related** — typed references to the other things the event involves. When
  an agent session emitted the event, that session is one of them.
- **causationid** — the id of the event that caused this one, when one did.

The id, type, source with its origin, subject and time are on every event a
current producer emits. Data, related references and a causation id are present
when the event has them; an absent attribute states nothing, and is never read
as unknown. An origin of none is a claim that the act happened in no registered
project, person or company; unknown makes no claim, and never passes as none or
as a guessed origin.

An event states nothing about where it will be handled. A home is where a
consumer works — a project's checkout, a person's or company's folder — and only
a consumer, on its own computer, decides from an event's origin whether the
event concerns one of its homes and which.

An event states facts only: what happened, and the status it reports. It
carries no notification rule, no action for anyone to take, no audience and no
routing scope. Each consumer decides its own reaction from the event's type,
source and origin, and subject, and reads the data only once the event has reached
it. Emission decides nothing about consumers and refuses nothing on the
strength of these facts.

A platform event that reports the state of a thing names that state in the last
segment of its type, under a family prefix shared by every state of that
lifecycle: a job's runs succeeded, failed or stalled are three states of one
family. The event catalog owns the closed set of state segments and marks each
one failing or ok, so a consumer reads a thing's state from the type alone. A
family that can report a thing failing also reports it ok, so everything that
can be reported broken has a reported way back; the correlation detections
report when their episode is over. The subject is the thing whose state is
reported, so a job's outcomes are about the job, not the single run, and every
state of one family states the same origin. An event
that reports no state of a thing, such as a dead-lettered stream entry, does not
end in a state segment. Events of published domains do not follow this
convention.

Every event type is declared once, as the type its producers construct. The
declaration states the type's name, what its events are about and the kind of
their subject, the origin kinds their origin can take or that the act happens
in no registered project, person or company, the data fields they carry with each field's value kind, the kinds of
thing their related references name, and, for a platform type that reports a
state, its family and whether the state is failing or ok. A producer can only
emit an event its type's declaration allows. The event catalog that
`telec events list` and `telec events schema` show is generated from these
declarations, so what an agent discovers is what producers emit.

Every attribute an event is emitted with travels with it unchanged to every
computer it reaches, whether or not that computer knows the named origin or the
named thing. Within one version of a type, change is additive: a reader ignores
attributes and data fields it does not know and tolerates absent ones that are
optional. A change that is not additive is a new version of the type, and event
records the platform keeps are migrated forward to it. Across computers
running different versions, the fleet's interoperability contract governs
(`local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`).

## Canonical fields

### Use cases

#### UC-EE1: Every event states its core facts

#### UC-EE2: An event's type says who owns it

#### UC-EE3: The subject names the thing and the origin names where it happened

#### UC-EE4: A project origin carries its owner as known where the event happened

#### UC-EE5: An event that cannot establish its origin says so

#### UC-EE6: An event carries facts and never instructions

#### UC-EE7: The emitting session and the causing event are references

#### UC-EE8: Emission decides nothing about consumers

#### UC-EE9: Every attribute arrives unchanged on every computer

#### UC-EE10: The catalog shows what producers emit

#### UC-EE11: A type evolves additively within its version

#### UC-EE12: Computers on different versions keep exchanging events

#### UC-EE13: One occurrence emitted twice carries one id

#### UC-EE14: A platform event's type names the state it reports

#### UC-EE15: Everything reported broken has a reported way back

## Known caveats

- **The origin is resolved from valid declarations.** The commit gate guarantees
  a valid declaration wherever its hooks are installed
  (`local/projects/teleclaude/spec/feature/config/project-capability-manifest`).
  An invalid declaration — committed in a registered project that carries no
  commit-gate hooks, or in a working copy broken mid-edit — is outside this
  contract.
- **Events from older computers name no subject.** Until every computer in the
  fleet emits this shape, a consumer keyed on the subject sees older computers'
  events without one.
- **Older readers keep their fields.** Until no live computer reads the earlier
  envelope, events also carry its fields in the shape older computers read
  (`local/projects/teleclaude/spec/domain/event-catalog`). They are not among the
  attributes this contract describes.
- **The origin travels under a field named `home`.** The delivered model and
  wire carry the origin's registered project, person or company in a field named
  `home`. The name states nothing about any consumer's home; the field is the
  event's origin.

## See Also

- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md — why the attributes follow CloudEvents, why the subject names the thing, and why conformance waits for an external consumer.
- docs/local/adr/0115-an-event-states-facts-and-its-consumers-own-every-reaction.md — why notification rules, action affordances and routing scope are not event facts.
- docs/local/adr/0117-a-platform-event-type-names-the-state-it-reports.md — why a platform event's state is the last segment of its type, and why every failing family declares an ok state.
- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why events state facts about themselves and receipt is decided on the receiving side.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why the origin distinguishes none from unknown.
- docs/local/adr/0118-an-event-states-its-origin-and-a-home-is-a-consumers.md — why an event states its origin and only a consumer resolves a home.
- docs/local/adr/0026-cross-version-fleet-compatibility.md — why the envelope evolves additively across a mixed-version fleet.
- docs/local/spec/domain/event-catalog.md — the catalog owns the envelope shape and the generated declarations; producing contexts own event meaning.
- docs/local/spec/feature/reconciliation/fleet-cross-version-interop.md — additive evolution of shared shapes across a mixed-version fleet.
- docs/local/spec/feature/identity/organizational-membership.md — what a project's declared owner means.
