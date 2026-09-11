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
<!-- planned:discord-personal-voice-conversation -->
- **Owns (live voice transport):** the personal Discord voice room's
  connection lifecycle, encrypted media transport across the two-process
  boundary, the explicit transmission framing that opens and closes one
  push-to-talk utterance, discarding audio from any speaker other than the
  configured person, and playback of a rendered audio artifact into the room.
  Utterance closure is provider protocol semantics and resolves here; a
  transmission without complete explicit closure produces no handoff.
- **Owns (voice connection ownership):** which computer holds the connection
  for a bot identity in a guild. A personal voice channel has no forum
  ancestry, so ownership is read from the person's declared voice
  configuration rather than derived from a project category. A peer that
  receives the same provider event performs no voice side effect.
- **Does not own (voice):** which session the person is listening to, what a
  session's spoken reply says, how audio is rendered, or whether a
  transcription becomes agent input. Integration hands a closed utterance to
  the established voice-input contract and plays what it is given.
<!-- /planned:discord-personal-voice-conversation -->
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

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
