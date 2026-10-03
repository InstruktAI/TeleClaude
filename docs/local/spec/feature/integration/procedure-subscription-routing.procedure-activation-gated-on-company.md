---
description: Platform events are matched, on the computer they originated on, against the procedure subscriptions that answer their subject's kind, and each match produces one activation naming the procedure and that subject; publication is what makes a subscription live, and a replayed event is not activated twice.
visibility: internal
---

# Procedure Subscription Routing — Spec

## What it is

Procedure subscription routing is the step between a platform event and the
agent that answers it. It consumes events from the platform event stream as
they reach this computer, and acts on an event only on the computer the event
originated on. There it matches the event against the published procedure
subscriptions and hands each match to the runtime contract that owns standing
agents, as one activation naming the procedure and the event's subject.
Routing decides nothing about whether an agent already stands, and never starts
or addresses a session itself.

An event states its own origin and subject
(`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`).
Routing reads both as stated and never constructs, replaces, or infers either.
Which computers an event reaches is decided by its producer's distribution; a
computer the event did not originate on does nothing with it, which is the
normal case rather than a failure. An event that names no origin, or whose
subject is unknown, activates nothing anywhere.

Every subscribed procedure declares the one kind of subject it answers:
company, person, project, or platform. It matches an event of a subscribed type
only when the event's subject is of that kind, and a platform procedure matches
events whose subject is none. A subject is never converted to another kind: a
project's subject does not reach its owning company's or person's procedures,
and a company's subject does not reach its projects' procedures.

A published subscription is live for the reach its publication tier gives it:
a procedure published at global tier answers every subject of its declared
kind, one published in a company's tier answers that company only, and one
published in a person's tier answers that person only. Publication is the
registration: nothing stands between an author declaring the events a
procedure answers to and those events reaching it.

An activation's identity is the event's own identity, the procedure, and the
subject. Routing the same event again for the same procedure and subject — a
retried stream entry, or an event reprocessed after a later stage failed —
reaches the activation that already exists instead of producing another, within
the records the platform retains. Routing runs before the event pipeline drops
events already projected as notifications, so a retry is never hidden from it.

## Canonical fields

### Use cases

#### UC-PSR1: A matched event produces one activation naming the procedure and subject

```gherkin
Given a published procedure declares an event type as activating it and answers events about a company
And an event of that type about a company is emitted on this computer
When the event is matched against the published procedure subscriptions
Then an agent inspecting the activation record sees exactly one activation naming that procedure and that company
And that activation carries the event's context
And the agent sees no session started or addressed by the match itself
```

#### UC-PSR2: Publication is the registration

```gherkin
Given a procedure declaring the events that activate it and the subject kind it answers is published
And no act beyond that publication has been performed
When an event of a declared type and kind is emitted on this computer
Then an agent inspecting the activation record sees an activation for that procedure and the event's subject
```

#### UC-PSR3: An unmatched event produces no activation

```gherkin
Given an event is emitted on this computer
And no published procedure declares its type
When the event is matched against the published procedure subscriptions
Then an agent inspecting the activation record sees no activation for that event
And sees no failure recorded for the absence of a match
```

#### UC-PSR4: A company-tier procedure answers only its company

```gherkin
Given two companies each publish in their own tier a procedure declaring the same event type and answering company events
When an event of that type about one of those companies is emitted on this computer
Then an agent inspecting the activation record sees an activation for that company only
And sees none for the other company
```

#### UC-PSR5: The activation names a system origin, not a fabricated human one

```gherkin
Given an event about a subject is emitted on this computer
When a match produces an activation for a published procedure
Then an agent inspecting the activation sees the platform's system principal named as its origin
And sees no human principal presented as having initiated it
```

#### UC-PSR7: Only the computer an event originated on activates it

```gherkin
Scenario Outline: A computer the event did not originate on produces no activation
  Given a procedure is published that answers an event type and its subject's kind
  And an event of that type reaches a computer that <relation to the event>
  When the event is matched against the published procedure subscriptions
  Then an agent inspecting that computer's activation record sees <outcome>
  And sees no failure recorded on any computer that produced no activation

  Examples:
    | relation to the event                                       | outcome                        |
    | emitted it                                                  | one activation for the event   |
    | did not emit it and holds the same home                     | no activation for the event    |
    | did not emit it and does not hold the home                  | no activation for the event    |
```

#### UC-PSR11: The subject's kind decides which procedures answer

```gherkin
Scenario Outline: An event activates the procedures that answer its subject's kind
  Given a global-tier procedure declaring an event type answers <declared kind> events
  And an event of that type is emitted on this computer about <event subject>
  When the event is matched against the published procedure subscriptions
  Then an agent inspecting the activation record sees <outcome>

  Examples:
    | declared kind | event subject                     | outcome                                          |
    | company       | a company                         | one activation naming the procedure and company  |
    | person        | a person                          | one activation naming the procedure and person   |
    | project       | a project                         | one activation naming the procedure and project  |
    | platform      | no registered home                | one activation naming the procedure and platform |
    | company       | a project that company owns       | no activation                                    |
    | person        | a project that person owns        | no activation                                    |
    | project       | a company                         | no activation                                    |
    | platform      | a project                         | no activation                                    |
```

#### UC-PSR12: An event that cannot establish its subject or origin activates nothing

```gherkin
Scenario Outline: Missing facts are never filled in
  Given a procedure is published that answers an event type for every subject kind it may declare
  And an event of that type <missing fact> reaches this computer
  When the event is matched against the published procedure subscriptions
  Then an agent inspecting the activation record sees no activation for the event
  And sees a routing decision naming the missing fact
  And sees no failure recorded for it

  Examples:
    | missing fact                                       |
    | emitted here, with an unknown subject              |
    | naming no originating computer                     |
```

#### UC-PSR13: A person-tier procedure answers only its person

```gherkin
Given a procedure published in a person's tier declares an event type and answers person events
When events of that type are emitted on this computer, one about that person and one about another person
Then an agent inspecting the activation record sees an activation for that person
And sees none for the other person
```

#### UC-PSR14: Routing the same event again produces no second activation

```gherkin
Scenario Outline: A repeat of one event reaches the existing activation
  Given an event emitted on this computer has produced an activation for a procedure and its subject
  When the same event reaches routing again because <reason>
  Then an agent inspecting the activation record still sees exactly one activation for that event, procedure, and subject
  And the procedure's standing agent has received the event once

  Examples:
    | reason                                                        |
    | its stream entry is redelivered                               |
    | a later stage of the event pipeline failed and it is retried  |
```

#### UC-PSR15: Distinct events stay distinct activations

```gherkin
Given a procedure answers an event type for a subject
When two distinct events of that type about that subject are emitted on this computer
Then an agent inspecting the activation record sees one activation for each event
And the procedure's standing agent receives both events
```

### Cross-context references

- **event-catalog** — owns the event envelope: the origin and subject this
  context reads, as the producer stated them, and the pipeline that carries an
  event to this context before notification deduplication.
- **context** — publishes the procedure subscriptions this context matches
  against, with the subject kind each answers and the tier each is published
  at; this context never inspects the documentation corpus itself or decides
  what may be published into it.
- **agent_runtime** — receives the activation and owns everything after it:
  whether an agent already stands, where the subject's home is and whether it
  exists on this computer, starting or waking the agent, and the principal and
  company it is bound to.

## Known caveats

- Matching establishes that a procedure's attention is due. It establishes
  nothing about whether a business mutation is necessary; a late or superseded
  event still reaches its agent and is reconciled by the activated procedure.
- Replay protection lasts as long as the platform retains the activation's
  operation and delivery records. A replay arriving after they are pruned is
  routed as a new activation.
- A computer whose daemon is not running when an event is emitted there misses
  that activation; no other computer stands in.
- A procedure published in a project's own tier is not part of the publication
  index this context matches against, so project subjects are answered by
  procedures published at global tier.

## See Also

- docs/local/adr/0110-an-event-activated-procedure-runs-where-its-event-originated.md — why only the origin computer activates.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why an unknown subject is never read as none.
- docs/local/spec/feature/event-catalog/event-envelope.md — the origin and subject every event carries.
