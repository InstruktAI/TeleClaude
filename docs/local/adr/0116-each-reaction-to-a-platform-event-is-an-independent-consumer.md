---
visibility: internal
number: 0116
date: 2026-10-08
description: Each reaction to a platform event is an independent consumer with its own progress through the stream, core-owned duplicate protection, a declared interest read only from event attributes, and its own bounded retry and dead letter; the system pipeline stops being where reactions live.
---

# Each Reaction to a Platform Event Is an Independent Consumer — ADR

## Context

Every computer reads the platform event stream through one consumer group and
runs each event through one system pipeline: trust, the integration trigger,
deduplication, enrichment, correlation, classification, the notification
projector and the lifecycle router, in that order. The stream entry is
acknowledged only after the last stage, and a failure anywhere retries the
whole chain.

Deduplication's only durable record is the notification row the projector
writes. A stage placed after the projector is therefore masked on retry: if
the lifecycle router fails after the row is written, the retry is dropped as a
duplicate and the dispatch it owed never happens. A stage placed before
deduplication sees every retry and must protect itself. Every new reaction has
to be placed in the chain with these effects in mind, and one failing reaction
delays every other.

Further reactions are being added: procedure activation, platform alerts and
domain notifications. Procedure subscriptions and person notification
preferences both select events by type pattern.

The stream already supports independent readers: a consumer group keeps its
own position and pending entries, and the existing processor already retries
with bounded attempts and dead-letters what keeps failing.

## Decision

- **Each reaction is a consumer.** It reads the platform event stream with its
  own progress on each computer, and its failure or lag never holds back or
  hides another consumer.
- **Duplicate protection belongs to the core.** A consumer is handed an event
  once per event id within the retained window; a redelivered stream entry or a
  re-emitted occurrence with the same id is not handed again. Consumers never
  deduplicate events themselves.
- **Interest is declared and read only from event attributes:** type patterns,
  whether the consumer acts only on events its own computer emitted, and the
  subject or home kinds it answers. The data is opaque to the selection.
- **One type-pattern matcher serves every selection.** A pattern is an exact
  type name, a whole-segment prefix followed by `.*`, or `*` for every type.
- **Retry and dead letter are per consumer.** A failing event is retried a
  bounded number of times, then parked where it can be inspected and announced;
  the consumer moves on to later events.
- **The system pipeline is not where reactions live.** The platform's own
  reactions outside notification — the integration trigger, the lifecycle
  router and correlation — become consumers.

## Consequences

- A consumer's correctness no longer depends on its position in a chain, and
  adding a reaction touches no other reaction.
- Each consumer reads every event on every computer, so the stream is read once
  per consumer rather than once per computer. Selection runs before any
  handling, so the cost of an uninteresting event is one attribute check.
- Duplicate protection lasts as long as the platform retains a consumer's
  handled-event records. A handler whose side effect lands but whose handling is
  interrupted before it is recorded is handed the event again, so side effects
  that must not repeat carry their own idempotency, such as a deterministic
  operation request id.
- The notification path stays a pipeline until the consumers that replace it
  exist; until then, two consumption models coexist.
- A new consumer starts from the events emitted after it first runs; it does
  not replay the stream's history.

## Alternatives Considered

- **Keep one pipeline and give each stage its own duplicate record.** Rejected:
  stages would still share one acknowledgement and one retry, so a failing stage
  keeps retrying every other stage and delays them.
- **One consumer group that fans out in process,** as the internal event bus
  delivers to its subscribers. Rejected: a fan-out shares one acknowledgement,
  so one subscriber's failure retries all of them, and none has a position of
  its own to resume from.
- **A stream per consumer, filled by producers.** Rejected: producers would
  have to know their consumers, which ADR-0115 rules out.
- **Selection by payload fields.** Rejected under ADR-0115: routing reads only
  event attributes.
