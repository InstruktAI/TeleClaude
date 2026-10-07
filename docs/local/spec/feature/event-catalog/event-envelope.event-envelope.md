---
description: Every platform event states, in one typed shape, what happened, which computer emitted it, the one thing it is about, the home that thing belongs to, and what else it involves; it states facts only, and each event type's declaration, from which the catalog is generated, says which of those facts its events carry.
visibility: internal
---

# Event Envelope — Spec

## What it is

Every event on the platform event stream describes itself with a small set of
attributes, set by its producer where the event happens:

- **id** — the event's own identity. A producer that can emit one occurrence
  more than once states the same id each time.
- **type** — what happened, as a dotted name whose first segment says who owns
  the type: `teleclaude` for what the platform itself emits, or the name of a
  published domain, such as `sdlc`, for that domain's events. An event from an
  external system enters through an inbound endpoint as an event of the domain
  its source declares.
- **source** — the computer the event was emitted on.
- **subject** — the one thing the event is about, as a typed reference: the kind
  of thing and its identity, such as a todo, a session, a job run or a computer.
- **time** — when it happened.
- **data** — the facts particular to the event's type.
- **home** — the registered project, person or company the event belongs to;
  none when it belongs to no registered home, such as an event about the
  platform itself; or unknown when the producer cannot establish it. A project
  home also carries its owner as resolved on the computer where the event
  happened: the owning company or person, no owner, or unresolved when that
  computer cannot read the project's ownership.
- **related** — typed references to the other things the event involves. When
  an agent session emitted the event, that session is one of them.
- **causationid** — the id of the event that caused this one, when one did.

The id, type, source, subject, time and home are on every event a current
producer emits. Data, related references and a causation id are present when
the event has them; an absent attribute states nothing, and is never read as
unknown. A home of none is a claim that the event belongs to no registered
home; unknown makes no claim, and never passes as none or as a guessed home.

An event states facts only: what happened, and the status it reports. It
carries no notification rule, no action for anyone to take, no audience and no
routing scope. Each consumer decides its own reaction from the event's type,
source, subject and home, and reads the data only once the event has reached
it. Emission decides nothing about consumers and refuses nothing on the
strength of these facts.

Every event type is declared once, as the type its producers construct. The
declaration states the type's name, what its events are about and the kind of
their subject, the home kinds their home can take or that they belong to no
home, the data fields they carry with each field's value kind, and the kinds of
thing their related references name. A producer can only emit an event its
type's declaration allows. The event catalog that `telec events list` and
`telec events schema` show is generated from these declarations, so what an
agent discovers is what producers emit.

Every attribute an event is emitted with travels with it unchanged to every
computer it reaches, whether or not that computer knows the named home or the
named thing. Within one version of a type, change is additive: a reader ignores
attributes and data fields it does not know and tolerates absent ones that are
optional. A change that is not additive is a new version of the type, and event
records the platform keeps are migrated forward to it. Across computers
running different versions, the fleet's interoperability contract governs
(`local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`).

## Canonical fields

### Use cases

#### UC-EE1: Every event states its core facts

```gherkin
Given a producer on a computer emits a platform event
When an agent consuming platform events receives it
Then it sees the event's id, its type, the computer that emitted it, its subject, when it happened, and its home
```

#### UC-EE2: An event's type says who owns it

```gherkin
Scenario Outline: The first segment of the type name is its owner
  Given <producer> emits an event
  When an agent consuming platform events reads its type
  Then the type name begins with "<first segment>"

  Examples:
    | producer                                                         | first segment |
    | the platform, about its own operation                            | teleclaude    |
    | the platform, about the sdlc domain it publishes                 | sdlc          |
    | an inbound endpoint, relaying a request whose source declares erp | erp           |
```

#### UC-EE3: The subject names the thing and the home names whose it is

```gherkin
Scenario Outline: Subject and home are separate facts
  Given <act> happens
  When the producer emits a platform event about it
  Then the event's subject is <subject>
  And its home is <home>

  Examples:
    | act                                                  | subject                    | home                          |
    | a todo of a registered project changes phase         | that todo                  | that project                   |
    | a session working in a registered person's folder ends | that session             | that person                   |
    | a job run executing for a registered project fails   | that job run               | that project                  |
    | the event stream's processor detects a failure burst | the computer it runs on    | none                          |
    | a session working in a folder no registration governs ends | that session         | none                          |
```

#### UC-EE4: A project home carries its owner as known where the event happened

```gherkin
Scenario Outline: The owner travels with the project home
  Given a platform event whose home is a registered project
  And that project is declared as owned by <declared owner>
  When an agent consuming platform events receives it
  Then the event names <owner on the event> as the project's owner

  Examples:
    | declared owner                                  | owner on the event       |
    | a company                                       | that company             |
    | a person                                        | that person              |
    | no one                                          | no owner                 |
    | a declaration the emitting computer cannot read | unresolved, never no owner |
```

#### UC-EE5: An event that cannot establish its home says so

```gherkin
Given a producer reports an act whose record was kept before the home it concerned was recorded with it
When the producer emits a platform event about that act
Then an agent consuming platform events sees that the event's home is unknown
And the event states neither none nor a guessed home
```

#### UC-EE6: An event carries facts and never instructions

```gherkin
Given a producer emits a platform event about an act that someone may want to respond to
When an agent consuming platform events reads it
Then it sees what happened and the status the event reports
And none of the event's attributes states a notification rule, an action to take, an audience or a routing scope
And the event type's declaration in the catalog states none of these either
```

#### UC-EE7: The emitting session and the causing event are references

```gherkin
Given an agent session emits a platform event while acting on an earlier event
When an agent consuming platform events reads it
Then the event's related references name that session
And its causation id is the id of the earlier event
And an event emitted by platform automation names no session among its related references
```

#### UC-EE8: Emission decides nothing about consumers

```gherkin
Given a producer emits a platform event whose home names a home some computers do not know
When the event is emitted
Then it is published as stated, without being refused, altered, or narrowed
And nothing about who may later receive it, or which computers it concerns, is decided at emission
```

#### UC-EE9: Every attribute arrives unchanged on every computer

```gherkin
Given a platform event emitted on one computer reaches another computer
When an agent on the receiving computer consumes it
Then it sees the same id, type, source, subject, time, home and owner, related references, causation id and data the producer stated
And this holds when the receiving computer does not know the named home or the named thing
```

#### UC-EE10: The catalog shows what producers emit

```gherkin
Given an event type is declared as the type its producers construct
When an agent reads that type in the event catalog
Then it sees the type's name, what its events are about and their subject kind, the home kinds their home can take or that they belong to no home, the data fields they carry with each field's value kind, and the kinds of thing their related references name
And every event a producer emits of that type carries attributes and data consistent with that declaration
```

#### UC-EE11: A type evolves additively within its version

```gherkin
Scenario Outline: Readers keep working as a type evolves
  Given a consumer reads events of a type
  When <change> to that type
  Then <outcome>

  Examples:
    | change                                             | outcome                                                                    |
    | a data field is added                              | the consumer ignores the field it does not know and processes the event  |
    | an optional data field is absent                   | the consumer processes the event without it                               |
    | a field is removed or its meaning changes          | the event is emitted as a new version of the type                         |
```

#### UC-EE12: Computers on different versions keep exchanging events

```gherkin
Given computers in the fleet run versions from before and after events carried subject, home, related references and causation ids as described here
When a computer that predates them receives an event carrying them
Then it processes the event as it did before, ignoring what it does not know
But when a computer that knows them receives an event from a computer that predates them
Then it reads the event's home from what that computer stated, and reads the event as naming no subject, no related references and no causation id, without error
```

#### UC-EE13: One occurrence emitted twice carries one id

```gherkin
Given a producer reports one occurrence
And it emits the event for that occurrence a second time, such as after an interrupted publish
When an agent consuming platform events receives both
Then both carry the same id
And two distinct occurrences never share an id
```

## Known caveats

- **The home is resolved from valid declarations.** The commit gate guarantees
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

## See Also

- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md — why the attributes follow CloudEvents, why the home moved out of the subject, and why conformance waits for an external consumer.
- docs/local/adr/0115-an-event-states-facts-and-its-consumers-own-every-reaction.md — why notification rules, action affordances and routing scope are not event facts.
- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why events state facts about themselves and receipt is decided on the receiving side.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why the home distinguishes none from unknown.
- docs/local/adr/0026-cross-version-fleet-compatibility.md — why the envelope evolves additively across a mixed-version fleet.
- docs/local/spec/domain/event-catalog.md — the catalog owns the envelope shape and the generated declarations; producing contexts own event meaning.
- docs/local/spec/feature/reconciliation/fleet-cross-version-interop.md — additive evolution of shared shapes across a mixed-version fleet.
- docs/local/spec/feature/identity/organizational-membership.md — what a project's declared owner means.
