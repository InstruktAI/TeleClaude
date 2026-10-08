---
description: Platform events are matched, on the computer that emitted them, against the procedure subscriptions whose type patterns they fit and that answer their home's kind, and each match produces one activation naming the procedure and that home; publication is what makes a subscription live, and an event handed again is not activated twice.
visibility: internal
---

# Procedure Subscription Routing — Spec

## What it is

Procedure subscription routing is the step between a platform event and the
agent that answers it. It runs as one consumer of the platform event stream on
each computer (`local/projects/teleclaude/spec/feature/event-catalog/event-consumers`),
interested in every event type, in events its own computer emitted, and in
events whose home is known. There it matches each event it is handed against
the published procedure subscriptions and hands each match to the runtime
contract that owns standing agents, as one activation naming the procedure and
the event's home. Routing decides nothing about whether an agent already
stands, and never starts or addresses a session itself.

An event states its own source, subject, and home
(`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`).
Routing reads them as stated and never constructs, replaces, or infers any of
them. Every computer reads the same stream; a computer that did not emit an
event does nothing with it, which is the normal case rather than a failure. An
event whose home is unknown activates nothing anywhere.

A procedure subscribes with type patterns: an exact event type name, a prefix
of whole name segments followed by `.*`, or `*`. A pattern matches an event's
type exactly as the event catalog's one type-pattern matcher matches it, so
`erp.invoice.*` matches `erp.invoice.paid` and `erp.invoice.overdue.reminded`
but neither `erp.invoices.paid` nor `erp.invoice`, and `erp.*` matches every
event of the `erp` domain.

Every subscribed procedure declares the one kind of home it answers: company,
person, project, or platform. It matches an event of a subscribed type only
when the event's home is of that kind, and a platform procedure matches events
whose home is none. A home is never converted to another kind: a project's home
does not reach its owning company's or person's procedures, and a company's
home does not reach its projects' procedures.

A published subscription is live for the reach its publication tier gives it:
a procedure published at global tier answers every home of its declared kind,
one published in a company's tier answers that company only, and one published
in a person's tier answers that person only. Publication is the registration:
nothing stands between an author declaring the events a procedure answers to
and those events reaching it.

An activation's identity is the event's id, the procedure, and the home.
Routing is handed an event once per event id; when its handling of an event is
interrupted and the event is handed again, every activation it already
produced for that event is found by its identity instead of produced again,
within the records the platform retains. When routing cannot submit an
activation, its handling of the event fails, and the consumer runtime retries
it and, when it keeps failing, parks and announces it.

## Canonical fields

### Use cases

#### UC-PSR1: A matched event produces one activation naming the procedure and home

```gherkin
Given a published procedure declares an event type as activating it and answers events whose home is a company
And an event of that type whose home is a company is emitted on this computer
When the event is matched against the published procedure subscriptions
Then an agent inspecting the activation record sees exactly one activation naming that procedure and that company
And that activation carries the event
And the agent sees no session started or addressed by the match itself
```

#### UC-PSR2: Publication is the registration

```gherkin
Given a procedure declaring the events that activate it and the home kind it answers is published
And no act beyond that publication has been performed
When an event of a declared type and home kind is emitted on this computer
Then an agent inspecting the activation record sees an activation for that procedure and the event's home
```

#### UC-PSR3: An unmatched event produces no activation

```gherkin
Given an event is emitted on this computer
And no published procedure declares a pattern its type fits
When the event is matched against the published procedure subscriptions
Then an agent inspecting the activation record sees no activation for that event
And sees no failure recorded for the absence of a match
```

#### UC-PSR4: A company-tier procedure answers only its company

```gherkin
Given two companies each publish in their own tier a procedure declaring the same event type and answering company events
When an event of that type whose home is one of those companies is emitted on this computer
Then an agent inspecting the activation record sees an activation for that company only
And sees none for the other company
```

#### UC-PSR5: The activation names a system origin, not a fabricated human one

```gherkin
Given an event with a known home is emitted on this computer
When a match produces an activation for a published procedure
Then an agent inspecting the activation sees the platform's system principal named as its origin
And sees no human principal presented as having initiated it
```

#### UC-PSR7: Only the computer that emitted an event activates it

```gherkin
Scenario Outline: A computer that did not emit the event produces no activation
  Given a procedure is published that answers an event type and its home's kind
  And an event of that type is read by a computer that <relation to the event>
  When the event is matched against the published procedure subscriptions
  Then an agent inspecting that computer's activation record sees <outcome>
  And sees no failure recorded on any computer that produced no activation

  Examples:
    | relation to the event                                       | outcome                        |
    | emitted it                                                  | one activation for the event   |
    | did not emit it and holds the same home                     | no activation for the event    |
    | did not emit it and does not hold the home                  | no activation for the event    |
```

#### UC-PSR11: The home's kind decides which procedures answer

```gherkin
Scenario Outline: An event activates the procedures that answer its home's kind
  Given a global-tier procedure declaring an event type answers <declared kind> events
  And an event of that type is emitted on this computer whose home is <event home>
  When the event is matched against the published procedure subscriptions
  Then an agent inspecting the activation record sees <outcome>

  Examples:
    | declared kind | event home                        | outcome                                          |
    | company       | a company                         | one activation naming the procedure and company  |
    | person        | a person                          | one activation naming the procedure and person   |
    | project       | a project                         | one activation naming the procedure and project  |
    | platform      | none                              | one activation naming the procedure and platform |
    | company       | a project that company owns       | no activation                                    |
    | person        | a project that person owns        | no activation                                    |
    | project       | a company                         | no activation                                    |
    | platform      | a project                         | no activation                                    |
```

#### UC-PSR12: An event whose home is unknown activates nothing

```gherkin
Given a procedure is published that answers an event type for every home kind it may declare
And an event of that type whose home is unknown is emitted on this computer
When the event reaches this computer's procedure subscription routing
Then an agent inspecting the activation record sees no activation for the event
And sees no failure recorded for it
```

#### UC-PSR13: A person-tier procedure answers only its person

```gherkin
Given a procedure published in a person's tier declares an event type and answers person events
When events of that type are emitted on this computer, one whose home is that person and one whose home is another person
Then an agent inspecting the activation record sees an activation for that person
And sees none for the other person
```

#### UC-PSR14: Handing the same event again produces no second activation

```gherkin
Scenario Outline: A repeat of one event reaches the existing activation
  Given an event emitted on this computer has produced an activation for a procedure and its home
  When <repeat>
  Then an agent inspecting the activation record still sees exactly one activation for that event, procedure, and home
  And the procedure's standing agent has received the event once

  Examples:
    | repeat                                                                     |
    | the stream delivers the event's entry again                                |
    | routing's handling of the event was interrupted and the event is handed again |
```

#### UC-PSR15: Distinct events stay distinct activations

```gherkin
Given a procedure answers an event type for a home
When two distinct events of that type whose home is that home are emitted on this computer
Then an agent inspecting the activation record sees one activation for each event
And the procedure's standing agent receives both events
```

#### UC-PSR16: A subscription selects a group of events by type pattern

```gherkin
Scenario Outline: A pattern matches whole name segments
  Given a global-tier procedure answering company events subscribes to "<pattern>"
  When an event of type "<type>" whose home is a company is emitted on this computer
  Then an agent inspecting the activation record sees <outcome>

  Examples:
    | pattern          | type                          | outcome                                          |
    | erp.invoice.paid | erp.invoice.paid              | one activation naming the procedure and company  |
    | erp.invoice.*    | erp.invoice.paid              | one activation naming the procedure and company  |
    | erp.invoice.*    | erp.invoice.overdue.reminded  | one activation naming the procedure and company  |
    | erp.invoice.*    | erp.invoices.paid             | no activation                                    |
    | erp.*            | erp.invoice.paid              | one activation naming the procedure and company  |
```

### Cross-context references

- **event-catalog** — owns the event envelope this context reads, the one
  type-pattern matcher it matches subscriptions with, and the consumer runtime
  that hands it each event once, keeps its progress, and retries and parks its
  failures.
- **context** — publishes the procedure subscriptions this context matches
  against, with the patterns each declares, the home kind each answers, and the
  tier each is published at; this context never inspects the documentation
  corpus itself or decides what may be published into it.
- **agent_runtime** — receives the activation and owns everything after it:
  whether an agent already stands, where the home is and whether it exists on
  this computer, starting or waking the agent, and the principal and company it
  is bound to.

## Known caveats

- Matching establishes that a procedure's attention is due. It establishes
  nothing about whether a business mutation is necessary; a late or superseded
  event still reaches its agent and is reconciled by the activated procedure.
- Replay protection lasts as long as the platform retains the consumer's record
  of the event and the activation's operation and delivery records. A repeat
  arriving after they are pruned is routed as a new activation.
- A computer whose daemon does not run again before the stream drops an event it
  emitted misses that activation; no other computer stands in.
- A procedure published in a project's own tier is not part of the publication
  index this context matches against, so project homes are answered by
  procedures published at global tier.

## See Also

- docs/local/adr/0110-an-event-activated-procedure-runs-where-its-event-originated.md — why only the emitting computer activates.
- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md — why the home, not the subject, names whose an event is.
- docs/local/adr/0116-each-reaction-to-a-platform-event-is-an-independent-consumer.md — why routing is an independent consumer.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why an unknown home is never read as none.
- docs/local/spec/feature/event-catalog/event-envelope.md — the source, subject, and home every event carries.
- docs/local/spec/feature/event-catalog/event-consumers.md — the consumer runtime and the type-pattern matcher.
