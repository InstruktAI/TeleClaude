---
visibility: internal
description: Frozen v1 ownership anchor for live agent sessions and supervised agent CLI processes.
---

# Agent Runtime Domain Spec — Spec

## What it is

The v1 agent-runtime area owns live agent sessions, tmux process supervision,
agent CLI launch and control, runtime status, and session lifecycle signals.
This repository is a maintenance-only appliance: its feature specs describe the
current contract, and replacement architecture is authoritative only in the
TeleClaudeNext repository.

## Canonical fields

- **Current behavior:** `docs/project/spec/feature/agent_runtime/`.
- **Implementation roots:** `teleclaude/core/session_*`,
  `teleclaude/core/tmux_bridge/`, `teleclaude/cli/tool_commands/sessions.py`,
  and `teleclaude/hooks/`.
- **Maintenance stance:** see `project/spec/domain/glossary`. No forward architecture is
  authored into this domain anchor.
- **Agent CLI hook contracts:** each supported runtime's hook surface — event
  vocabulary, payload shapes, per-event context-injection and activity
  capability, and stdout protocol — is consolidated as third-party
  documentation, one root per runtime. It is the authority for what a runtime
  emits and accepts; the adapters under `teleclaude/hooks/adapters/` implement
  against it and never restate it. Discover with `telec docs index --third-party`
  and fetch with `telec docs get`.

### Ownership boundary

<!-- planned-change:external-session-identity -->
- **Owns:** live-session acceptance and input execution, supervised agent
  processes, runtime status, and session lifecycle transitions.
<!-- change:external-session-identity -->
- **Owns:** live-session acceptance and input execution, supervised agent
  processes, runtime status, session lifecycle transitions, and the root
  process binding held for a session whose agent process this runtime did not
  launch — the immutable process instance that defines which process tree the
  session owns.
<!-- /planned-change:external-session-identity -->
- **Does not own:** provider transport or presentation, caller-identity policy,
  todo workflow, or durable historical projections.
<!-- planned:discord-personal-voice-conversation -->
- **Owns (voice focus):** the association between one identified human and the
  single live session they are currently listening to. Focus follows that
  human's most recent accepted input across origins; activity that is not
  accepted human input never moves it. An explicit selection overrides the
  derived value without creating agent input, and is durable because selection
  and input are separate acts. An utterance latches the focused session at the
  moment its transmission begins, so a later focus change cannot redirect an
  utterance already under way.
- **Published contracts (voice focus):** a command that sets focus explicitly
  for a human, a query returning the currently focused session for a human, and
  the existing session-input delivery contract through which a closed
  voice-originated utterance is accepted. Integration reaches focus only
  through these; it never reads or writes the association directly.
- **Focus authority is the listening computer.** The record lives with the
  computer that owns the person's voice connection, because that is the one
  deciding what to play. Its derived input ordering comes from cluster session
  snapshots, which already publish the identified human and the time input was
  last accepted; an explicit selection supersedes the derived value until a
  later accepted input from that human.
- **Also published:** a query returning a session's complete user-visible final
  response together with the output version it belongs to; and the session
  observation contract — a peer registers renewable, bounded interest in a live
  session, and on that session's agent stop this runtime sends the observing
  peer a notification naming the session and its output-stop version. The
  runtime publishes both halves; what an observer does with the notification is
  the observer's own contract. The published
  snapshot carries the generated summary and an output digest, neither of which
  is the spoken contract, so this is the contract a remote listener reads. It is
  additive: existing queries and payloads are unchanged.
<!-- /planned:discord-personal-voice-conversation -->
<!-- planned-change:external-session-identity -->
- **Published contracts:** session commands, queries, and lifecycle signals
  exposed to integration, workflow, identity, and session mirrors.
<!-- change:external-session-identity -->
- **Published contracts:** session commands, queries, and lifecycle signals
  exposed to integration, workflow, identity, and session mirrors. Two serve
  caller attestation: a command binding a session's root to the process instance
  the daemon attested as the enrolling peer, and a query returning the open
  sessions whose root occurs in a supplied verified ancestry, each with the depth
  at which it was found. The query reports what it found and chooses nothing;
  which of them authorizes the caller is the identity context's rule. The identity context
  reaches both only through these contracts, never by reading hook internals,
  the native-session map, or session storage directly.
<!-- /planned-change:external-session-identity -->

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
