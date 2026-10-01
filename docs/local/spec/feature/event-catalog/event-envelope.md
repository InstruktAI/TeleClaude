---
description: Every platform event states where it came from and what it is about — its origin and its subject — and every catalog event type declares its subject assignment and payload fields, so consumers can route, scope, and narrow on facts the event carries about itself.
visibility: internal
delivered_by:
  - event-origin-and-subject
---

# Event Envelope — Spec

## What it is

Every event on the platform event stream describes itself with two facts, set by
its producer where the event happens:

- **Origin** — where the event came from: the computer it was emitted on, and,
  when an agent session emitted it, that session and the session's registered
  home (a project, person, or company).
- **Subject** — what the event is about: the registered project, person, or
  company it concerns; none when it concerns no registered home, such as the
  platform itself; or unknown when the event does not carry it. A project
  subject also carries its owner as resolved on the computer where the event
  happened: the owning company or person, no owner, or unresolved when that
  computer cannot read the project's ownership.

An event states none only when it concerns no registered home, so a consumer
reading none can rely on that. An event that does not know its subject states
unknown instead, and never passes as one about no home.

Both are facts about the event, never about its consumers. A producer does not
decide, assume, or check who will receive an event, and emission refuses nothing
on the strength of these facts. Platform automation has no home of its own; its
events carry no session origin, and their subject is the home of what the
automation acted on. Who may receive an event is decided on the receiving side
from its subject (`local/projects/teleclaude/spec/feature/agent_runtime/event-subscriptions` is
one such consumer); this contract only guarantees the facts are there.

Every event type in the catalog declares its subject assignment — what its
events are about and the home kinds that subject can take, or none for a type
whose events concern no registered home — and the payload fields its events
carry. The
declaration is the discovery surface for what a consumer may filter or narrow
on; each event carries a subject and payload consistent with its type's
declaration.

The origin and subject an event is emitted with travel with it unchanged to
every computer it reaches, whether or not that computer knows the named home.

## Canonical fields

### Use cases

#### UC-EE1: An event emitted by an agent session names that session and its home

```gherkin
Given an agent session working in a registered home emits a platform event
When an agent consuming platform events receives it
Then the event names the computer it was emitted on
And it names the emitting session
And it names that session's registered home as a project, person, or company

Examples:
  | session works in                      | origin home         |
  | a registered project checkout         | that project        |
  | a registered person's folder          | that person         |
  | a registered company's folder         | that company        |
  | a folder no registration governs      | none                |
```

#### UC-EE2: An event emitted by platform automation names only its computer

```gherkin
Given platform automation with no session behind it emits a platform event
When an agent consuming platform events receives it
Then the event names the computer it was emitted on
And it names no emitting session and no origin home
```

#### UC-EE3: An event about a registered home names that home as its subject

```gherkin
Given platform automation or an agent session acts on something that belongs to a registered home
When it emits a platform event about that act
Then the event's subject is that home, as a project, person, or company
And an automation event's subject is the home of what it acted on, even though the automation itself worked in no home
```

#### UC-EE4: A project subject carries its owner as known where the event happened

```gherkin
Given a platform event whose subject is a registered project
When an agent consuming platform events receives it
Then the event names the project's owner as it was resolved on the emitting computer

Examples:
  | project declared as owned by | owner named on the event |
  | a company                    | that company             |
  | a person                     | that person              |
  | no one                       | no owner                 |
  | a declaration the emitting computer cannot read | unresolved, never no owner |
```

#### UC-EE5: An event that concerns no registered home carries no subject

```gherkin
Given a producer emits a platform event that concerns no registered home
When an agent consuming platform events receives it
Then the event states that it has no subject

Examples:
  | the event concerns                                    |
  | the platform itself, such as daemon or stream health  |
  | a session working in a folder no registration governs |
```

#### UC-EE6: Emission decides nothing about consumers

```gherkin
Given a producer emits a platform event whose subject names a home some computers do not know
When the event is emitted
Then it is published as stated, without being refused, altered, or narrowed
And nothing about who may later receive it is decided at emission
```

#### UC-EE7: Origin and subject arrive unchanged on every computer

```gherkin
Given a platform event emitted on one computer reaches another computer
When an agent on the receiving computer consumes it
Then it sees the same origin, subject, and subject owner the producer stated
And this holds when the receiving computer does not know the named home
```

#### UC-EE8: Every event type declares its subject assignment and payload fields

```gherkin
Given an agent reads the event catalog's declaration for any event type
When it looks up what events of that type are about and what they carry
Then the declaration states what those events are about and which home kinds that subject can take, or that they concern no registered home
And it lists the payload fields events of that type carry
And every event of that type carries a subject and payload fields consistent with its type's declaration
```

#### UC-EE9: Computers on different versions keep exchanging events

```gherkin
Given computers in the fleet run versions from before and after events carried origin and subject
When a computer that predates these facts receives an event carrying them
Then it processes the event as before, ignoring the facts it does not know
But when a computer that knows these facts receives an event from one that predates them
Then it reads that event as having no emitting session, no origin home, and an unknown subject, without error
```

#### UC-EE10: An event about an act recorded before its home was kept states its subject as unknown

```gherkin
Given a producer reports an act whose record was kept before the home it concerned was recorded with it
When the producer emits a platform event about that act
Then an agent consuming platform events sees that the event's subject is unknown
And the event states neither no subject nor a guessed home
```

## Known caveats

- **The subject is as truthful as the declarations it is resolved from.** None
  can be relied on while the declaration governing the act is valid, which the
  commit gate guarantees wherever its hooks are installed
  (`local/projects/teleclaude/spec/feature/config/project-capability-manifest`).
  An invalid declaration is outside this contract: in a registered project that
  carries no commit-gate hooks, or in a working copy broken mid-edit, an event
  about that project may state none.

## See Also

- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why events state origin and subject as facts about themselves, why access follows the subject, why a project subject carries its owner, and why emission validates nothing.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why the subject distinguishes none from unknown, and why events from older computers read as unknown.
- docs/local/adr/0026-cross-version-fleet-compatibility.md — why origin and subject evolve additively and older events read as carrying neither.
- ~/.teleclaude/docs/sdlc/principle/architectural-defaults.md — event-driven decoupling: producers publish facts, consumers decide their own reaction.
- docs/local/spec/domain/event-catalog.md — the catalog owns envelope shape and discovery metadata; producing contexts own event meaning.
- docs/local/spec/feature/identity/organizational-membership.md — what a project's declared owner means.
- docs/local/spec/feature/reconciliation/fleet-cross-version-interop.md — additive evolution of shared shapes across a mixed-version fleet.
- docs/local/spec/feature/agent_runtime/event-subscriptions.md — a consumer that decides receipt from the subject.
