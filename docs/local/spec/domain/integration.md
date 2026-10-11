---
visibility: internal
description: Frozen v1 ownership anchor for external-provider and process-boundary integration behavior.
---

# Integration Domain Spec — Spec

## What it is

The v1 integration area inventories behavior crossing provider, process, and
delivery boundaries, including inbound adapters, outbound notifications, agent
hook reception, and code-integration workflow surfaces. Its feature specs and
implementation remain the current appliance contract.

## Canonical fields

- **Current behavior:** `docs/local/spec/feature/integration/`.

- **Implementation roots:** `teleclaude/adapters/`,
  `teleclaude/core/integration/`, and `teleclaude/core/inbound/`.

- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. No replacement transport design is
  authored here.

### Ownership boundary

- **Owns:** provider and process transport, inbound normalization, outbound
  delivery mechanics, and translation across external boundaries.
- **Does not own:** session-input acceptance or execution, identity policy,
  todo lifecycle, or presentation policy merely because integration carries
  the message.
- **Owns (live voice transport):** the personal Discord voice room's
  connection lifecycle, encrypted media transport across the two-process
  boundary, the explicit transmission framing that opens and closes one
  push-to-talk utterance, discarding audio from any speaker other than the
  configured person, and playback of a rendered audio artifact into the room.
  Utterance closure is provider protocol semantics and resolves here: the
  sender-emitted stop sequence is the push-to-talk release and the only close,
  and an absent or unorderable sequence produces no handoff.
- **Owns (voice connection ownership):** which computer holds the connection
  for a bot identity in a guild. A personal voice channel has no forum
  ancestry, so ownership is not derived from a project category; it follows
  the mesh master — the one computer that already provisions this bot's
  shared Discord structure — and a peer that receives the same provider event
  performs no voice side effect.
- **Does not own (voice):** which session the person is listening to, what a
  session's spoken reply says, how audio is rendered, or whether a
  transcription becomes agent input. Integration hands a closed utterance to
  the established voice-input contract and plays what it is given.
- **Published contracts:** normalized inbound commands and events, outbound
  delivery requests and results, and provider-neutral transport types.

- **Owns (procedure subscription routing):** reading each published procedure
  subscription — its type patterns, the home kind it answers, the agent
  identity it declares, and the tier it is published in — from the publication
  index `context` publishes; and running,
  on each computer, one platform event consumer that is handed the events its
  own computer emitted whose origin is known, and matches each event's type and
  origin against those subscriptions with `event-catalog`'s type-pattern matcher.
  A procedure answers only events whose origin is of its declared kind, with a
  platform procedure answering events whose origin is none, and a tier-published
  procedure only its own company or person. Each match produces one activation:
  the procedure, the event's origin, the event, the agent identity the
  procedure declares, and the platform's system principal as its origin,
  identified by the event's id, the procedure, and the home so that handling
  the same event again finds the existing activation.
  Routing reads the event's source, origin and subject as its producer stated
  them and never constructs, replaces, or converts any of them; it coordinates
  no computers. An event another computer emitted and an event whose origin is
  unknown produce no activation and record no failure. A submission that fails
  fails the consumer's handling of the event, which the consumer runtime retries
  and parks. The subscription set is held in memory with the identity of the
  index it came from and re-read when the published index changes, so an
  added, edited, or removed subscription takes effect at the next event without
  a restart or a separate trigger. Editing a procedure's subscriptions changes
  its event membership and never the identity of its agent.

- **Also owns (attendance in the activation):** each activation carries the
  attendance its procedure declares, attended when undeclared, read from the
  same published subscription as its agent identity; routing decides nothing
  about it.

<!-- planned:procedure-event-delivery -->

- **Also owns (delivery declarations in activations):** carrying the effective
  delivery policy from context's published subscription into the runtime
  activation command, under
  `local/projects/teleclaude/spec/feature/integration/procedure-subscription-routing`.
  Routing derives no defaults and makes no hook eligibility decisions.

<!-- /planned:procedure-event-delivery -->

- **Also owns (internal handler boundary):** an internal handler receives the
  matched contract alongside the event, so a handler serving several contracts
  knows which one matched when subscriptions overlap.

- **Does not own (procedure activation):** whether a standing agent exists,
  starting or waking it, or the identity it runs under. For each match, the
  activation consumer's first act submits the activation to `agent_runtime` as
  a command addressed to its own computer with a durable operation receipt, so
  the operation exists before any fallible step. It takes no further decision.

- **Owns (conversation entry, adapter side):** recognising an entry identifier
  in what a person sent — however the adapter carries it — and handing it to the
  core; on a per-computer adapter, keeping its lookup of a person's latest
  session by origin metadata; and delivering to the endpoint the core returns
  (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`).
- **Does not own (conversation entry):** resolving an identifier to an endpoint,
  the endpoint registry, the neutral reply, which computer acts, or the
  escalation relay — the core's (`agent_runtime`); whether a home runs a desk
  (`config`); what a desk session may read (`context`).

- **Owns (telling people about events):** the consumers that tell people —
  incident alerts for platform events and subscribed domain events for a
  published domain's events — and what each decides: which events it tells, to
  which recipients within their reach, and when an open matter is closed; the
  incident record of open matters per lifecycle family and thing; the record of
  which selected people a domain event has reached, kept with the event's
  handled record; and composing each message from the event's facts and its type's
  declaration, or its type name when it has none
  (`local/projects/teleclaude/design/architecture/notification-delivery`,
  `local/projects/teleclaude/spec/feature/integration/incident-alerts`,
  `local/projects/teleclaude/spec/feature/integration/subscribed-domain-events`,
  `local/projects/teleclaude/spec/feature/integration/notification-messages`).
  Messages go out through person-addressed delivery; nothing about telling
  people is stored or shown on a shared surface.

- **Does not own (telling people about events):** a person's notification
  interests or whether they select a type (`config`); the lifecycle state
  vocabulary, the type-pattern matcher, or the consumer runtime
  (`event-catalog`); who is a platform administrator or what a principal may
  see (`identity`); what an event means (its producing context).

- **Owns (help-desk Discord surface):** on the master, each hosted desk's
  Discord category and its three channels. This covers the per-person grants
  that turn the desk's scope into Discord visibility and channel abilities,
  re-syncing those grants when a declaration they derive from changes, and
  mirroring each desk session into its own desk's customer-sessions forum
  (`local/projects/teleclaude/spec/feature/integration/discord-admin-reflection-state`).
  A desk forum is no entry point: a post Discord lets through into a desk's
  customer-sessions thread reaches no session.
- **Does not own (help-desk Discord surface):** who is in a desk's scope
  (`identity`); which desks this computer hosts (`agent_runtime`'s endpoint
  registry); whether a home keeps a desk, or a person's Discord binding
  (`config`); a desk session's lifecycle or its escalation relay
  (`agent_runtime`).

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
