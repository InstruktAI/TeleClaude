---
description: Every reaction to a platform event runs as an independent consumer that
  is handed each event it declares interest in once, keeps its own progress through
  the stream, and retries and dead-letters its own failures without delaying or hiding
  any other consumer.
visibility: internal
---

# Event Consumers — Spec

## What it is

A consumer is one reaction to events on one computer. Public platform reactions
and internal runtime reactions use the same independent-consumer delivery
mechanics, with source streams kept separate under
`local/projects/teleclaude/design/architecture/event-delivery`.
Each consumer keeps its own progress through its bound source, so its failure
or lag never holds back or hides another consumer.

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

A pattern in any other form is refused where it is declared, and the refusal
names the invalid pattern so its author can correct the declaration
(`general/policy/agent-facing-text`). Every context that lets an author select
events by type pattern matches with this one matcher, so a pattern means the
same wherever it is written.

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

The platform's own reactions — waking the lifecycle runner, spawning the
integrator, correlating failures into degradation events, and telling people
about events — are consumers. Each acts only on events its own computer emitted,
so a failure is correlated, a degradation announced, and a person told, once, by
the computer it happened on.

Maintenance a project binds to its own events is a platform reaction that acts
on every computer, whichever computer emitted the event: each computer holding
the project's canonical checkout performs the bound actions on its own checkout
(`local/projects/teleclaude/spec/feature/integration/event-bound-maintenance`).

## Canonical fields

### Domain notification delivery

Domain notifications between the runtime, integration and adapters use declared
events and independent consumers. Each consumer is bound to a source stream and
its codec under `local/projects/teleclaude/design/architecture/event-delivery`.
Progress, ordering, retries and duplicate handling apply to that bound source.
Consumer identities are unique across the computer's shared handled-event store.
The consumer runtime is
the sole executor of their reactions; producers hold no immediate
subscriber-dispatch path. This division
follows `sdlc/principle/architectural-defaults` and
`sdlc/policy/domain-ownership`.

Commands and runtime-local coordination retain their owning capabilities; the
relationship is defined by
`local/projects/teleclaude/design/architecture/event-delivery`.

### Use cases

#### UC-EC1: One consumer's failure does not hold back another

#### UC-EC2: A repeated event is handed to a consumer once

#### UC-EC3: Interrupted handling is handed again

#### UC-EC4: A consumer that acts on its own computer's events ignores the rest

#### UC-EC5: Type patterns select at whole-segment boundaries

#### UC-EC6: A malformed pattern is refused where it is declared

#### UC-EC7: Selection reads only event attributes

#### UC-EC8: An event that keeps failing is parked and announced

#### UC-EC9: A consumer that was down catches up

#### UC-EC10: A new consumer starts from the present

#### UC-EC11: A workflow reaction is not lost when notification fails

#### UC-EC12: Each computer correlates its own failures

### Cross-context references

- **event-catalog** — owns the envelope attributes consumers select on and the
  event a dead letter is announced with.
- **workflow** — owns both of its reactions: the lifecycle runner the lifecycle
  router wakes, and the integrator the integration trigger spawns, with its
  singleton lease. Each starts sessions through `agent_runtime`'s dispatch
  contract, and neither consumer decides which todo is dispatched or
  integrated.

- **integration** — owns the consumers that tell people, procedure activation
  and event-bound maintenance, each a consumer under its own contract.

- **context** and **identity** — a context that lets authors select events by
  type pattern owns that declaration and matches it with this matcher.

## Known caveats

- Duplicate protection lasts while the platform retains a consumer's record of
  handled events; a repeat arriving after that is handed again.

- Each consumer reads every event in its bound source stream, so that source
  is read once per consumer bound to it.

## See Also

- docs/local/adr/0116-each-reaction-to-a-platform-event-is-an-independent-consumer.md — why every reaction is an independent consumer with core-owned duplicate protection.
- docs/local/adr/0115-an-event-states-facts-and-its-consumers-own-every-reaction.md — why selection reads only event attributes.
- docs/local/spec/feature/event-catalog/event-envelope.md — the attributes consumers select on.
