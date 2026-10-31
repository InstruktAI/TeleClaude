---
description: Every reaction to a platform event runs as an independent consumer that
  is handed each event it declares interest in once, keeps its own progress through
  the stream, and retries and dead-letters its own failures without delaying or hiding
  any other consumer.
visibility: internal
---

# Event Consumers — Spec

## What it is

A consumer is one reaction to events on one computer. Its owner declares whether
that reaction retains individual occurrences or consumes live notifications.
Public platform reactions
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

### Retained occurrences

Retained consumers use independent ordered progress and the existing stream
retention window. The platform hands such a consumer each event it is interested
in once. A stream
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

<!-- planned:cluster-redis-outage-store-and-forward -->

A cluster event emitted while its computer cannot reach the cluster Redis
(`local/projects/teleclaude/design/architecture/event-delivery`, Scopes and
their Redis) is accepted and held on that computer, and its emission does not
fail. Once the cluster Redis answers, the held events reach the stream in the
order the computer emitted them, before any cluster event it emits afterwards,
and a retained consumer on another computer handles each from its own progress.
A held event survives a restart of the daemon and of the computer's own Redis,
so an event emitted during the outage arrives late and is not lost. A computer
whose local and cluster events share one Redis holds nothing.

<!-- /planned:cluster-redis-outage-store-and-forward -->

<!-- planned-change:event-driven-lifecycle-runner -->

The platform's own reactions — waking the lifecycle runner, spawning the
integrator, correlating failures into degradation events, and telling people
about events — are consumers. Each acts only on events its own computer emitted,
so a failure is correlated, a degradation announced, and a person told, once, by
the computer it happened on.
<!-- change:event-driven-lifecycle-runner -->

The platform's own reactions — waking the lifecycle runner, spawning the
integrator, correlating failures into degradation events, and telling people
about events — are consumers. Each acts only on events its own computer emitted,
so a failure is correlated, a degradation announced, and a person told, once, by
the computer it happened on. One reaction acts on another computer's event: the
named computer's pickup acts on the event naming it a project's active
computer, whichever computer emitted it
(`local/projects/teleclaude/design/architecture/work-pickup`).
<!-- /planned-change:event-driven-lifecycle-runner -->

Maintenance a project binds to its own events is a platform reaction that acts
on every computer, whichever computer emitted the event: each computer holding
the project's canonical checkout performs the bound actions on its own checkout
(`local/projects/teleclaude/spec/feature/integration/event-bound-maintenance`).

## Canonical fields

### Live notifications and source recovery

Live consumers start from a captured current stream position. They retain no
consumer-group pending entries or handled-event records and do not replay
historical presentation after restart. Their in-memory read window is bounded;
obsolete frames may be omitted. A failed live reaction is logged and does not
retry obsolete presentation or end the daemon. Delivery lifetime follows the
consumer's actual effect under `sdlc/policy/domain-ownership`.

A live consumer representing current state declares its authoritative recovery
operation. It captures its stream position before recovering source state and
processes subsequent notifications only after recovery succeeds. Connection
failure repeats that handover. Such a consumer may coalesce a batch by event
type, source and subject when its handler reconciles the full current state.
Transient feedback declares no recovery operation and intentionally omits missed
presentation. These distinctions follow `sdlc/principle/design-fundamentals`.

An existing retained position is retired only by the same computer's owning
consumer after its replacement recovery succeeds, or after the owner declares
the effect to be transient feedback. Retirement does not mark historical events
handled or alter another consumer's ledger. Accepted commands, operation/control
delivery and public occurrence consumers retain their owning durable contracts.

### Domain notification delivery

Domain notifications between the runtime, integration and adapters use declared
events and independent consumers. Each consumer is bound to a source stream and
its codec under `local/projects/teleclaude/design/architecture/event-delivery`.
Each reaction applies its declared lifetime to that bound source. Retained
delivery owns ordered progress, retries and duplicate records; live delivery
owns its current boundary and source recovery.
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

- Retained occurrences are recoverable only within their source stream's
  retention window. Missing payloads cannot establish that an effect completed;
  their failure remains visible through the existing recovery and dead-letter
  contracts.
- A live read window bounds frame count rather than elapsed latency. A slow
  reaction can delay its own reader; it does not create a retained replay
  obligation for obsolete presentation.

- Duplicate protection lasts while the platform retains a consumer's record of
  handled events; a repeat arriving after that is handed again.

- Each consumer reads every event in its bound source stream, so that source
  is read once per consumer bound to it.

## See Also

- docs/local/adr/0116-each-reaction-to-a-platform-event-is-an-independent-consumer.md — why every reaction is an independent consumer with core-owned duplicate protection.
- docs/local/adr/0115-an-event-states-facts-and-its-consumers-own-every-reaction.md — why selection reads only event attributes.
- docs/local/spec/feature/event-catalog/event-envelope.md — the attributes consumers select on.
