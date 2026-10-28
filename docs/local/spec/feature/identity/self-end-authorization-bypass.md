---
description: Allow a parentless session to end itself via `telec sessions end`, bypassing
  the normal clearance band; sub-worker self-end and cross-session end fall through
  to the standard rule.
visibility: public
---

# Self-End Authorization Bypass — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

`telec sessions end` is normally restricted to the orchestrator/integrator system band — focused-role agent sessions are excluded. But a runner-dispatched driver session (an analyzer, a prepare/work orchestrator) is authorization-classified as `focused`, holds the todo's `active_runner` lease, and must end itself to release that lease and wake the runner. Command clearance for `telec sessions end` therefore recognises a "self-end" shape — a caller resolved to a session, ending that same session, whose session record names no orchestrating parent (`initiator_session_id is None`) — and admits it without consulting the verb allowlist. Every other shape falls through to the standard rule: a sub-worker self-end (parent set) and a cross-session end are evaluated against the normal band, and a focused session is refused there. The decision is made in the CLI process before any request is sent (`feature/identity/command-clearance`); the daemon performs the end it receives.

The driver-vs-sub-worker discriminator is `initiator_session_id`. It is daemon-set session state, populated when an orchestrator dispatches a child that takes its work from that dispatcher; runner-dispatched drivers, human-started sessions, and standing roles — the integrator, the project coordinator, a scheduled job runner — carry `None`, because their work arrives from a queue, a schedule, or the fleet rather than from whoever started them (`local/projects/teleclaude/spec/feature/agent_runtime/session-authority`). Clearance reads it from the caller's own session record, never from a value the caller supplies, so a sub-worker cannot claim a parentless row to widen its own authority. This mirrors the self-restart carve-out, which grants a worker the right to restart only itself.

## Canonical fields

### Use cases

#### UC-SE1: Parentless driver ends itself

#### UC-SE2: Sub-worker self-end is rejected

#### UC-SE3: A focused session ending another session is rejected

#### UC-SE4: Orchestrator/integrator ends another session

#### UC-SE5: Terminal caller follows the standard human band

### Cross-context references

- This is the session-end flow leaning on command clearance for a single carve-out, the end-path counterpart of `feature/identity/self-restart-authorization-bypass`.
- The carve-out relies on the client-side caller resolution (`local/projects/teleclaude/spec/identity-and-auth` §6) having resolved the caller to its session record — terminal callers cannot self-end via the carve-out and go through the standard human band.
- `initiator_session_id` is the same driver-vs-sub-worker discriminator the session-lifecycle contract relies on (drivers hold the `active_runner` and are reaped on close; sub-workers are reaped by their orchestrator).
- The session authority rule the daemon applies to the end it performs is unchanged by this carve-out: a session never ends the orchestrator that dispatched it (`local/projects/teleclaude/spec/feature/agent_runtime/session-authority`).

## Known caveats

- The carve-out widens `telec sessions end` for the caller's OWN session only, and only when `initiator_session_id is None`. The deny path is preserved verbatim for cross-session end by any non-band role and for self-end by a parented sub-worker.
- The carve-out applies ONLY when the caller resolves to a session and the target is exactly that session. Terminal callers (no session) and callers acting on a different session go through the standard rule.
- `initiator_session_id` is daemon-set session state read from the caller's own record, so a focused session cannot supply a parentless row to gain cross-session end authority. The only path the carve-out opens to a focused session is ending its own parentless session.
- The refusal names the caller's role (`"role '<role>' is not permitted to call telec sessions end"`), identical to the standard rule's message.
