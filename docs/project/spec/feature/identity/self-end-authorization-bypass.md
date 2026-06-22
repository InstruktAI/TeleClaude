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

`telec sessions end` is normally restricted to the orchestrator/integrator system band — worker-role agent sessions are excluded. But a runner-dispatched driver session (an analyzer, a prepare/work orchestrator) is authorization-classified as a `worker`, holds the todo's `active_runner` lease, and must end itself to release that lease and wake the runner. The self-end clearance gate solves this by recognising a "self-end" shape — an authenticated caller whose own `session_id` equals the target `session_id` and whose target session has no orchestrating parent (`initiator_session_id is None`) — and returning the resolved `CallerIdentity` without consulting the verb allowlist. Every other shape falls through to the standard rule: a sub-worker self-end (parent set) and a cross-session end are evaluated against the normal band, and a worker is rejected there.

The driver-vs-sub-worker discriminator is `initiator_session_id`. It is daemon-set session state, populated only when an orchestrator dispatches a child via `telec sessions run`; runner-dispatched drivers and human-started sessions carry `None`. Because it is never caller-supplied, a sub-worker cannot forge a parentless row to widen its own authority. This mirrors the self-restart carve-out, which grants a worker the right to restart only itself.

## Canonical fields

### Use cases

#### UC-SE1: Parentless driver ends itself

```
Given a worker agent session with system_role=`worker` and initiator_session_id=None
When the session issues `telec sessions end` for its own session_id
Then the self-end gate accepts (session ids match, no orchestrating parent)
And the clearance gate returns the CallerIdentity without consulting the standard verb allowlist
And the end proceeds with HTTP 202
```

#### UC-SE2: Sub-worker self-end is rejected

```
Given a worker agent session with system_role=`worker` and initiator_session_id set to its orchestrating parent
When the session issues `telec sessions end` for its own session_id
Then the self-end gate rejects (the session has an orchestrating parent)
And the standard rule fires: the worker is not in the `telec sessions end` system band
And the response is HTTP 403 not-permitted for `telec sessions end`
```

#### UC-SE3: Worker ending another session is rejected

```
Given a worker agent session with system_role=`worker`
When the session issues `telec sessions end` for a DIFFERENT session_id
Then the self-end gate rejects (session_id mismatch)
And the standard rule fires: the worker is not in the `telec sessions end` system band
And the response is HTTP 403 not-permitted for `telec sessions end`
```

#### UC-SE4: Orchestrator/integrator ends another session

```
Given an agent session whose system_role is in the `telec sessions end` system band (e.g. `integrator`)
When the session issues `telec sessions end` for a DIFFERENT session_id
Then the self-end gate rejects (session_id mismatch)
And the standard verb-clearance evaluation accepts the in-band role
And the cross-session end proceeds with HTTP 202
```

#### UC-SE5: Terminal caller follows the standard human band

```
Given a terminal caller with CallerIdentity.session_id="" (no owning session)
When it issues `telec sessions end` for a session
Then the self-end gate is skipped (`identity.session_id` is empty)
And the standard rule runs against the caller's human_role
And admin/member callers pass with HTTP 202; others are rejected
```

### Cross-context references

- This is the session-end flow leaning on the identity context for a single carve-out, the end-path counterpart of `feature/identity/self-restart-authorization-bypass`.
- The bypass relies on the token-path resolution from `feature/identity/caller-verification` having populated `identity.session_id` — terminal callers cannot self-end via the carve-out and go through the standard human band.
- `initiator_session_id` is the same driver-vs-sub-worker discriminator the session-lifecycle contract relies on (drivers hold the `active_runner` and are reaped on close; sub-workers are reaped by their orchestrator).

## Known caveats

- The carve-out widens `telec sessions end` for the caller's OWN session only, and only when `initiator_session_id is None`. The deny path is preserved verbatim for cross-session end by any non-band role and for self-end by a parented sub-worker.
- The bypass works ONLY when `identity.session_id` is non-empty and exactly equals the target session_id. Terminal callers (no session) and dual-factor callers acting on a different session go through the standard rule.
- `initiator_session_id` is daemon-set session state, never caller-supplied, so a worker cannot forge a parentless row to gain cross-session end authority. The only path the carve-out opens to a worker is ending its own parentless session.
- The authorization-failure message echoes the caller's role back to the wire (`"role '<role>' is not permitted to call telec sessions end"`), identical to the standard rule's message, so the wire contract is unchanged on the deny path.
