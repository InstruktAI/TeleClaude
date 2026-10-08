---
description: Every reaction to a platform event runs as an independent consumer that is handed each event it declares interest in once, keeps its own progress through the stream, and retries and dead-letters its own failures without delaying or hiding any other consumer.
visibility: internal
delivered_by:
  - consumer-framework
---

# Event Consumers — Spec

## What it is

A consumer is one reaction to platform events on one computer: activating
procedures, telling people, waking the lifecycle runner, spawning the
integrator, correlating failures. Each consumer reads the platform event stream
with its own progress on that computer, so its failure or lag never holds back
or hides another consumer.

A consumer declares its interest in terms of event attributes only
(`local/projects/teleclaude/spec/feature/event-catalog/event-envelope`):

- the **types** it handles, as patterns;
- whether it acts only on events **its own computer emitted**, read from the
  event's source;
- optionally, the **subject kinds** or **origin kinds** it answers.

An event outside that interest is passed over without being handed to the
consumer. The event's data is read only by the consumer it is handed to.

A type pattern is one of:

- an exact type name, which matches that type only;
- a prefix of whole name segments followed by `.*`, which matches every type
  that starts with that prefix and has at least one more segment;
- `*`, which matches every type.

A pattern in any other form is refused where it is declared. Every context that
lets an author select events by type pattern matches with this one matcher, so a
pattern means the same wherever it is written.

The platform hands a consumer each event it is interested in once. A stream
entry delivered again, or an occurrence re-emitted with the same id, is not
handed a second time while the platform retains the consumer's record of the
event. A consumer never deduplicates events itself. An event whose handling was
interrupted before it completed is handed again; a handler whose side effect
must not repeat makes that side effect idempotent.

When handling fails, the platform retries it a bounded number of times. An event
that keeps failing is parked as that consumer's dead letter, where it can be
inspected, and the platform emits an event naming the consumer and the parked
event. The consumer then continues with later events. A consumer handles events
in stream order, and a parked event never blocks the ones after it.

A consumer that is not running while events are emitted resumes from its own
progress when it runs again, for as long as the stream retains those events. A
consumer that runs for the first time starts with the events emitted from then
on; it does not replay the stream's history.

The platform's own reactions outside notification — waking the lifecycle runner,
spawning the integrator, and correlating failures into degradation events — are
consumers. Each acts only on events its own computer emitted, so a failure is
correlated, and a degradation announced, once, by the computer it happened on.

## Canonical fields

### Use cases

#### UC-EC1: One consumer's failure does not hold back another

```gherkin
Given two consumers on a computer are both interested in an event type
And one of them fails while handling an event of that type
When the event reaches that computer
Then the other consumer handles the event once, without waiting for the failing one
And the failing consumer's retries do not hand the event to the other consumer again
```

#### UC-EC2: A repeated event is handed to a consumer once

```gherkin
Scenario Outline: The platform recognizes a repeat by the event's id
  Given a consumer has handled an event
  When <repeat>
  Then the consumer is not handed the event again

  Examples:
    | repeat                                                          |
    | the stream delivers the same entry again                        |
    | the producer emits the same occurrence again with the same id   |
```

#### UC-EC3: Interrupted handling is handed again

```gherkin
Given a consumer is handling an event
When its handling is interrupted before it completes, such as by a daemon restart
Then the consumer is handed the event again when it next runs
```

#### UC-EC4: A consumer that acts on its own computer's events ignores the rest

```gherkin
Given a consumer declares that it acts only on events its own computer emitted
When an event of a type it handles reaches that computer
Then it handles the event when the event's source is that computer
And it passes the event over when the event's source is another computer
```

#### UC-EC5: Type patterns select at whole-segment boundaries

```gherkin
Scenario Outline: A pattern matches whole segments only
  Given a consumer declares interest in the type pattern "<pattern>"
  When an event of type "<type>" reaches it
  Then the consumer <outcome>

  Examples:
    | pattern          | type                          | outcome          |
    | erp.invoice.paid | erp.invoice.paid              | handles it       |
    | erp.invoice.*    | erp.invoice.paid              | handles it       |
    | erp.invoice.*    | erp.invoice.overdue.reminded  | handles it       |
    | erp.invoice.*    | erp.invoices.paid             | passes it over   |
    | erp.invoice.*    | erp.invoice                   | passes it over   |
    | erp.*            | erp.invoice.paid              | handles it       |
    | *                | teleclaude.session.ended      | handles it       |
```

#### UC-EC6: A malformed pattern is refused where it is declared

```gherkin
Scenario Outline: Only exact names, whole-segment prefixes and the bare wildcard are patterns
  Given an author declares the type pattern "<pattern>"
  When the declaration is validated
  Then it is refused with a reason naming the pattern

  Examples:
    | pattern         |
    | erp.inv*        |
    | erp.*.paid      |
    | *.paid          |
```

#### UC-EC7: Selection reads only event attributes

```gherkin
Given a consumer declares interest by type pattern, source, and subject or origin kind
When an event reaches it
Then whether it is handed the event depends only on the event's type, source and origin, and subject
And the event's data is never read before the event is handed to the consumer
```

#### UC-EC8: An event that keeps failing is parked and announced

```gherkin
Given a consumer fails to handle an event on every attempt
When the platform's retry limit is reached
Then the event is parked as that consumer's dead letter, where an agent can inspect it
And the platform emits an event naming the consumer and the parked event
And the consumer goes on to handle the events after it
```

#### UC-EC9: A consumer that was down catches up

```gherkin
Given a consumer is not running while events it is interested in are emitted
When it runs again while the stream still retains those events
Then it handles each of them once, in stream order
```

#### UC-EC10: A new consumer starts from the present

```gherkin
Given events were emitted before a consumer first ran on a computer
When the consumer first runs there
Then it handles only events emitted from then on
```

#### UC-EC11: A workflow reaction is not lost when notification fails

```gherkin
Scenario Outline: The platform's own reactions do not depend on notification
  Given an event emitted on a computer calls for <reaction>
  And telling people about that event fails on that computer
  When the event is processed there
  Then <reaction> happens once on that computer

  Examples:
    | reaction                                      |
    | the lifecycle runner being woken              |
    | the integrator being spawned                  |
```

#### UC-EC12: Each computer correlates its own failures

```gherkin
Given failure events of one type about one thing are emitted on a computer within the correlation window
When their number crosses the degradation threshold
Then that computer emits one degradation event for that thing
And no other computer emits a degradation event for those failures
```

### Cross-context references

- **event-catalog** — owns the envelope attributes consumers select on and the
  event a dead letter is announced with.
- **workflow** — owns both of its reactions: the lifecycle runner the lifecycle
  router wakes, and the integrator the integration trigger spawns, with its
  singleton lease. Each starts sessions through `agent_runtime`'s dispatch
  contract, and neither consumer decides which todo is dispatched or
  integrated.

- **integration** — owns the notification path that runs as the system
  pipeline, and procedure activation, which is a consumer under its own
  contract.

- **context** and **identity** — a context that lets authors select events by
  type pattern owns that declaration and matches it with this matcher.

## Known caveats

- Duplicate protection lasts while the platform retains a consumer's record of
  handled events; a repeat arriving after that is handed again.
- Every consumer reads every event on its computer, so the stream is read once
  per consumer.
- Until the notification path is itself a set of consumers, it runs as the
  system pipeline beside them.

## See Also

- docs/local/adr/0116-each-reaction-to-a-platform-event-is-an-independent-consumer.md — why every reaction is an independent consumer with core-owned duplicate protection.
- docs/local/adr/0115-an-event-states-facts-and-its-consumers-own-every-reaction.md — why selection reads only event attributes.
- docs/local/spec/feature/event-catalog/event-envelope.md — the attributes consumers select on.
