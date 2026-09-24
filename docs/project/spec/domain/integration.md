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

- **Current behavior:** `docs/project/spec/feature/integration/`.
- **Implementation roots:** `teleclaude/adapters/`,
  `teleclaude/core/integration/`, `teleclaude/core/inbound/`, and
  `teleclaude/events/delivery/`.
- **Maintenance stance:** see `project/spec/domain/glossary`. No replacement transport design is
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

<!-- planned:procedure-event-activation -->
- **Owns (procedure subscription routing):** stamping a verified event, at the
  ingress and before it is relayed, with the company `config` declares for its
  source; turning each published procedure subscription into a contract in the
  existing contract-routing model that carries the procedure's canonical ID;
  and, on each computer, matching the event against those contracts only when
  `config` answers that the event's company is configured on that computer,
  producing one activation per match: the procedure, the company, the event's
  context, and the platform's system principal as its origin. A computer that
  does not host the company, and any computer receiving an event with no
  company, produces no activation and records no failure. The event names no
  consumer; each computer decides for itself and nothing coordinates them.
  Procedure-subscription contracts are derived state: held only in the
  registry's memory, never persisted or restored from storage, and rebuilt from
  the publication index `context` publishes. They are derived when the
  activation handler registers, keyed to the digest of the index they came
  from; before matching an event, the router compares that digest with the
  currently published index and re-derives when they differ. A procedure
  contract therefore never exists without the handler that serves it, and an
  added, edited, or removed subscription takes effect at the next event without
  a restart or a separate trigger. Editing a procedure's subscriptions changes
  its event membership and never the procedure-and-company identity of its
  agent.
- **Also owns (internal handler boundary):** an internal handler receives the
  matched contract alongside the event, so a handler serving several contracts
  knows which one matched when subscriptions overlap.
- **Does not own (procedure activation):** whether a standing agent exists,
  starting or waking it, or the identity it runs under. The activation
  handler's first act submits the activation to `agent_runtime` as a command
  addressed to its own computer with a durable operation receipt, so the
  operation exists before any fallible step; a submission that itself fails is
  emitted as a platform error event. It takes no further decision.
<!-- /planned:procedure-event-activation -->

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
