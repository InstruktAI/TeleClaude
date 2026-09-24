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
<!-- planned-change:external-session-identity -->
- **Published contracts:** normalized inbound commands and events, outbound
  delivery requests and results, and provider-neutral transport types.
<!-- change:external-session-identity -->
- **Published contracts:** normalized inbound commands and events, outbound
  delivery requests and results, provider-neutral transport types, and the
  attested-caller signal — the kernel-held peer identity of the process on the
  other end of a local connection, normalized at connection-accept and supplied
  to identity. Integration carries that evidence and never interprets it: which
  session owns the process is agent_runtime's answer, and what the caller is
  authorized to do is identity's.
<!-- /planned-change:external-session-identity -->

<!-- planned:procedure-event-activation -->
- **Owns (procedure subscription routing):** turning each published procedure
  subscription into a contract in the existing contract-routing model, matching
  verified events against those contracts for the company the event's
  configured source is associated with, and producing one activation per match:
  the procedure, that company, the event's context, and the platform's system
  principal as its origin. The contract's target is an internal activation
  handler, so a match and its activation run on the computer that received the
  event.
- **Does not own (procedure activation):** whether a standing agent exists,
  starting or waking it, or the identity it runs under. The activation handler
  hands each activation to `agent_runtime` as a computer-addressed command
  through the command-dispatch contract and takes no further decision.
<!-- /planned:procedure-event-activation -->

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
