---
id: project/spec/feature/identity/self-restart-authorization-bypass
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Allow any authenticated session to restart itself via `POST /sessions/{id}/agent-restart`, bypassing the normal `telec sessions restart` clearance.
---

# Self-Restart Authorization Bypass — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The `POST /sessions/{session_id}/agent-restart` route is the one place where v1 deliberately diverges from the verb-based clearance rule. Normally `telec sessions restart` is restricted (notably, worker-Role agent sessions are excluded), but a worker that has gone unresponsive must be able to recover itself. The `clearance_sessions_agent_restart` gate solves this by recognising a "self-restart" shape — an authenticated caller whose own session_id matches the URL's session_id and whose JSON body carries `self_restart: true` — and returning the resolved CallerIdentity without consulting the verb allowlist at all. Every other shape (cross-session restart, missing flag, wrong content-type) falls through to the standard rule and a worker is then explicitly rejected before the generic verb check runs.

## Canonical fields

### Use cases

```
Given a worker agent session with CallerIdentity.session_id=`8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f` and system_role=`worker`
When the session issues `POST /sessions/8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f/agent-restart` with `Content-Type: application/json` and body `{"self_restart": true}`
Then `_is_self_agent_restart_request` returns True (session ids match, JSON body, flag truthy)
And `clearance_sessions_agent_restart` returns the CallerIdentity without consulting `is_command_allowed`
And the route proceeds to dispatch the restart
```

```
Given the same worker session
When it issues `POST /sessions/c3f1d8a2-7b94-4e6c-9f0e-2a8d7b6c4e5f/agent-restart` (a DIFFERENT session id) with `{"self_restart": true}`
Then `_is_self_agent_restart_request` returns False (session_id mismatch)
And the standard rule fires: `identity.system_role == ROLE_WORKER` short-circuits to 403
And the response is HTTPException(403, "role 'worker' is not permitted to call telec sessions restart")
```

```
Given an orchestrator-Role agent session (system_role=`orchestrator`) whose Role is in the `telec sessions restart` system band
When it issues `POST /sessions/<other-session-id>/agent-restart` with any body
Then `_is_self_agent_restart_request` returns False (session_id mismatch)
And `is_command_allowed("telec sessions restart", orchestrator, …)` returns True
And the dependency returns the CallerIdentity and the cross-session restart proceeds
```

```
Given a worker session
When it issues `POST /sessions/8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f/agent-restart` with `Content-Type: application/json` and body `{"self_restart": false}`
Then `_is_self_agent_restart_request` returns False (flag not truthy)
And the standard worker-short-circuit raises HTTPException(403)
```

```
Given a worker session
When it issues `POST /sessions/8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f/agent-restart` with `Content-Type: text/plain` and body `self_restart=true`
Then `_is_self_agent_restart_request` returns False (content-type is not `application/json`)
And the standard worker-short-circuit raises HTTPException(403)
```

```
Given a terminal caller with CallerIdentity.session_id="" (no owning session)
When it issues `POST /sessions/<any>/agent-restart` with `{"self_restart": true}`
Then `_is_self_agent_restart_request` returns False (`identity.session_id` is empty)
And the standard rule runs against the caller's human_role
And admin/member callers pass; others receive 403
```

### Implementation pointers (v1)

- Self-restart shape predicate: `teleclaude/api/auth.py:329-340` (`_is_self_agent_restart_request`)
- Composite gate (bypass + worker short-circuit + standard check): `teleclaude/api/auth.py:343-358` (`clearance_sessions_agent_restart`)
- Route binding: `teleclaude/api/sessions_actions_routes.py:457-461`
- Route handler that re-reads `self_restart` from the body to pass to `restart_agent`: `teleclaude/api/sessions_actions_routes.py:478-487`

### Cross-context references

- This is `agent_runtime`'s session-restart flow leaning on identity for a single carve-out. The route handler dispatches `get_command_service().restart_agent(cmd)` in `agent_runtime` after identity clears it.
- The bypass relies on the token-path Resolution from `feature/identity/caller-verification` having populated `identity.session_id` — terminal callers cannot self-restart anything.
- In v2 the carve-out disappears from identity. `agent_runtime` defines its own "may restart self" authorization rule and evaluates it against the resolved `Principal`. Identity returns the Principal only; the cross-cutting verb table no longer needs a special case.

## Known caveats

- The request body is read twice: once by `_is_self_agent_restart_request` (to check `self_restart`) and again by the route handler (to forward `self_restart` to `restart_agent`). Starlette caches `request.json()` so both reads return the same parsed payload, but a custom `Request` subclass that disables caching would fail the second read.
- The bypass works ONLY when `identity.session_id` is non-empty and exactly equals the URL's `session_id`. Terminal callers (no session) and dual-factor callers acting on a different session must go through the standard rule.
- The worker short-circuit is intentional defence-in-depth. Even if a future change added `worker` to `CommandAuth.system` for `telec sessions restart`, the explicit `identity.system_role == ROLE_WORKER` check in `clearance_sessions_agent_restart` still rejects cross-session restarts by workers. The only path open to a worker is the self-restart bypass.
- The content-type match is strict: `application/json` after splitting on `;` and lowercasing, so `application/json; charset=utf-8` is accepted but `text/json` is not.
- The `self_restart` payload is matched with `payload.get("self_restart") is True` — strict identity against the singleton `True`. The JSON boolean `true` (which parses to Python `True`) passes; the strings `"true"`, `"1"`, the integer `1`, and any other truthy value all fail. The route handler that re-reads the body uses the laxer `bool(body.get("self_restart"))` form, so a caller could in principle pass the standard rule's worker short-circuit (with a non-bool truthy value rejected at the bypass), get a 403, and never reach the laxer handler-side coercion.
