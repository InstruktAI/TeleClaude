---
description: Allow a parentless session to end itself via `telec sessions end`, bypassing
  the normal clearance band; sub-worker self-end and cross-session end fall through
  to the standard rule.
visibility: public
---

# Self-End Authorization Bypass — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

`telec sessions end` is normally restricted to the orchestrator/integrator system band — worker-role agent sessions are excluded. But a runner-dispatched driver session (an analyzer, a prepare/work orchestrator) is authorization-classified as a `worker`, holds the todo's `active_runner` lease, and must end itself to release that lease and wake the runner. Command clearance for `telec sessions end` therefore recognises a "self-end" shape — a caller resolved to a session, ending that same session, whose session record names no orchestrating parent (`initiator_session_id is None`) — and admits it without consulting the verb allowlist. Every other shape falls through to the standard rule: a sub-worker self-end (parent set) and a cross-session end are evaluated against the normal band, and a worker is refused there. The decision is made in the CLI process before any request is sent (`feature/identity/command-clearance`); the daemon performs the end it receives.

The driver-vs-sub-worker discriminator is `initiator_session_id`. It is daemon-set session state, populated when an orchestrator dispatches a child that takes its work from that dispatcher; runner-dispatched drivers, human-started sessions, and standing roles — the integrator, the project coordinator, a scheduled job runner — carry `None`, because their work arrives from a queue, a schedule, or the fleet rather than from whoever started them (`project/spec/feature/agent_runtime/session-authority`). Clearance reads it from the caller's own session record, never from a value the caller supplies, so a sub-worker cannot claim a parentless row to widen its own authority. This mirrors the self-restart carve-out, which grants a worker the right to restart only itself.

## Canonical fields

### Use cases

#### UC-SE1: Parentless driver ends itself

```
Given a worker agent session with system_role=`worker` and initiator_session_id=None
When the session issues `telec sessions end` for its own session_id
Then clearance admits the self-end (the target is the caller's own session, with no orchestrating parent)
And the standard verb allowlist is not consulted
And the session is ended
```

#### UC-SE2: Sub-worker self-end is rejected

```
Given a worker agent session with system_role=`worker` and initiator_session_id set to its orchestrating parent
When the session issues `telec sessions end` for its own session_id
Then the self-end shape does not apply (the session has an orchestrating parent)
And the standard rule refuses the worker, which is not in the `telec sessions end` system band
And the refusal is the not-permitted failure for `telec sessions end`, given before any request is sent
```

#### UC-SE3: Worker ending another session is rejected

```
Given a worker agent session with system_role=`worker`
When the session issues `telec sessions end` for a DIFFERENT session_id
Then the self-end shape does not apply (the target is another session)
And the standard rule refuses the worker, which is not in the `telec sessions end` system band
And the refusal is the not-permitted failure for `telec sessions end`, given before any request is sent
```

#### UC-SE4: Orchestrator/integrator ends another session

```
Given an agent session whose system_role is in the `telec sessions end` system band (e.g. `integrator`)
When the session issues `telec sessions end` for a DIFFERENT session_id
Then the self-end shape does not apply
And the standard verb clearance admits the in-band role
And the other session is ended
```

#### UC-SE5: Terminal caller follows the standard human band

```
Given an operator at a terminal, outside any session
When they issue `telec sessions end` for a session
Then the self-end shape does not apply (the caller is not a session)
And the standard rule runs against the person's role
And admin/member callers end the session; others are refused before any request is sent
```

### Cross-context references

- This is the session-end flow leaning on command clearance for a single carve-out, the end-path counterpart of `feature/identity/self-restart-authorization-bypass`.
- The carve-out relies on the client-side caller resolution (`project/spec/identity-and-auth` §6) having resolved the caller to its session record — terminal callers cannot self-end via the carve-out and go through the standard human band.
- `initiator_session_id` is the same driver-vs-sub-worker discriminator the session-lifecycle contract relies on (drivers hold the `active_runner` and are reaped on close; sub-workers are reaped by their orchestrator).
- The session authority rule the daemon applies to the end it performs is unchanged by this carve-out: a session never ends a session above it (`project/spec/feature/agent_runtime/session-authority`).

## Known caveats

- The carve-out widens `telec sessions end` for the caller's OWN session only, and only when `initiator_session_id is None`. The deny path is preserved verbatim for cross-session end by any non-band role and for self-end by a parented sub-worker.
- The carve-out applies ONLY when the caller resolves to a session and the target is exactly that session. Terminal callers (no session) and callers acting on a different session go through the standard rule.
- `initiator_session_id` is daemon-set session state read from the caller's own record, so a worker cannot supply a parentless row to gain cross-session end authority. The only path the carve-out opens to a worker is ending its own parentless session.
- The refusal names the caller's role (`"role '<role>' is not permitted to call telec sessions end"`), identical to the standard rule's message.
