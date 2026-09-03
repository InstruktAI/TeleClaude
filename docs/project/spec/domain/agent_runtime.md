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
<!-- planned-change:external-session-identity -->
- **Published contracts:** session commands, queries, and lifecycle signals
  exposed to integration, workflow, identity, and session mirrors.
<!-- change:external-session-identity -->
- **Published contracts:** session commands, queries, and lifecycle signals
  exposed to integration, workflow, identity, and session mirrors. Two serve
  caller attestation: a command minting a session's root process binding from
  evidence the daemon attested, and a query returning the open sessions whose
  root occurs in a supplied verified ancestry. The query returns the matching
  set, never a chosen winner; selecting among several is not a runtime
  decision, and identity refuses rather than picking. The identity context
  reaches both only through these contracts, never by reading hook internals,
  the native-session map, or session storage directly.
<!-- /planned-change:external-session-identity -->

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
