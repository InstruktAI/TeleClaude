---
id: 'project/spec/feature/identity/self-restart-authorization-bypass'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Allow any authenticated session to restart itself via the agent-restart action, bypassing the normal `telec sessions restart` clearance.'
---

# Self-Restart Authorization Bypass — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The agent-restart action is the one place where v1 deliberately diverges from the verb-based clearance rule. Normally `telec sessions restart` is restricted (notably, worker-Role agent sessions are excluded), but a worker that has gone unresponsive must be able to recover itself. The agent-restart clearance gate solves this by recognising a "self-restart" shape — an authenticated caller whose own session_id matches the target session_id and whose request payload carries `self_restart: true` — and returning the resolved CallerIdentity without consulting the verb allowlist at all. Every other shape (cross-session restart, missing flag, wrong payload encoding) falls through to the standard rule, and a worker is then explicitly rejected before the generic verb check runs.

## Canonical fields

### Use cases

```
Given a worker agent session with CallerIdentity.session_id=`8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f` and system_role=`worker`
When the session issues an agent-restart action for its own session_id with a structured payload `{"self_restart": true}`
Then the self-restart predicate accepts (session ids match, structured payload, flag truthy)
And the agent-restart clearance gate returns the CallerIdentity without consulting the standard verb allowlist
And the action proceeds to dispatch the restart
```

```
Given the same worker session
When it issues an agent-restart action targeting a DIFFERENT session_id with `{"self_restart": true}`
Then the self-restart predicate rejects (session_id mismatch)
And the standard rule fires: the worker short-circuit rejects the call
And the response is a not-permitted authorization failure for `telec sessions restart`
```

```
Given an orchestrator-Role agent session (system_role=`orchestrator`) whose Role is in the `telec sessions restart` system band
When it issues an agent-restart action targeting another session with any payload
Then the self-restart predicate rejects (session_id mismatch)
And the standard verb-clearance evaluation accepts the orchestrator
And the dependency returns the CallerIdentity and the cross-session restart proceeds
```

```
Given a worker session
When it issues a self-targeted agent-restart with a structured payload `{"self_restart": false}`
Then the self-restart predicate rejects (flag not truthy)
And the worker short-circuit rejects the call
```

```
Given a worker session
When it issues a self-targeted agent-restart with a non-structured payload (e.g. text encoding) carrying `self_restart=true`
Then the self-restart predicate rejects (payload encoding is not structured)
And the worker short-circuit rejects the call
```

```
Given a terminal caller with CallerIdentity.session_id="" (no owning session)
When it issues an agent-restart action with `{"self_restart": true}`
Then the self-restart predicate rejects (`identity.session_id` is empty)
And the standard rule runs against the caller's human_role
And admin/member callers pass; others are rejected
```

### Cross-context references

- This is `agent_runtime`'s session-restart flow leaning on the identity context for a single carve-out. The action handler dispatches the agent restart inside `agent_runtime` after the identity context clears it.
- The bypass relies on the token-path resolution from `feature/identity/caller-verification` having populated `identity.session_id` — terminal callers cannot self-restart anything.
- The agent-restart action also emits an `agent_runtime.agent.restarted` event on successful dispatch (see the v2 event taxonomy).
- In v2 the carve-out disappears from identity. `agent_runtime` defines its own "may restart self" authorization rule and evaluates it against the resolved `Principal`. Identity returns the Principal only; the cross-cutting verb table no longer needs a special case.

## Known caveats

- The request payload is read twice: once by the self-restart predicate (to check `self_restart`) and again by the action handler (to forward `self_restart` to the restart capability). The inbound transport caches parsed payloads so both reads return the same value, but a transport variant that disables caching would fail the second read.
- The bypass works ONLY when `identity.session_id` is non-empty and exactly equals the target session_id. Terminal callers (no session) and dual-factor callers acting on a different session must go through the standard rule.
- The worker short-circuit is intentional defence-in-depth. Even if a future change added `worker` to the system band for `telec sessions restart`, the explicit worker check in the agent-restart clearance gate still rejects cross-session restarts by workers. The only path open to a worker is the self-restart bypass.
- The payload-encoding match is strict (structured / JSON-style only); other encodings are refused even if they would carry a syntactically truthy `self_restart` value.
- The `self_restart` payload is matched with strict identity against the singleton `True`. The structured boolean `true` (which parses to a Python `True`) passes; the strings `"true"`, `"1"`, the integer `1`, and any other truthy value all fail. The action handler that re-reads the payload uses a looser truthy coercion, so a caller could in principle pass the standard rule's worker short-circuit (with a non-bool truthy value rejected at the bypass), get rejected, and never reach the looser handler-side coercion.
