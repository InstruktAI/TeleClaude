---
id: 'project/spec/feature/identity/session-access-visibility'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Authorize web-frontend session-scoped API calls against the session owner, the session''s shared/private visibility, and the caller''s role.'
---

# Session Access & Visibility — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The per-session authorization rule for web-frontend callers. Once the trust boundary admits a request carrying `x-web-user-email` / `x-web-user-role`, every route handler that operates on a specific session calls `check_session_access(request, session_id, require_owner=?)` before doing any work. The function decides three things in one pass: does this session exist, may this web user see it, and — for owner-only operations — may this web user end it. Owner-only operations (currently `DELETE /sessions/{id}`) require either the session's owner email or the admin role. Standard operations (read messages, send a message, send keys/voice, restart the agent, revive, tail the transcript, stream) allow the owner, an admin, OR any member-role caller when the owner has flipped the session's `visibility` to `shared`. CLI / tool / agent callers that arrive without identity headers bypass the check entirely — they are already gated by `verify_caller`'s session-token and terminal-email paths. The `shared` visibility flag is the cooperation primitive: it is the owner's explicit "this session is okay for my teammates to read and act on" — without that flag, every session is private to its owner.

## Canonical fields

### Use cases

```
Given a web user with email maurice@instrukt.ai and role admin
And a session 7c6a1f80-e4d1-4d24-bf12-3a1b9d2e0e44 owned by anyone
When any session-scoped route calls check_session_access(request, "7c6a1f80-e4d1-4d24-bf12-3a1b9d2e0e44")
Then the function returns immediately on the admin-bypass branch
And the route proceeds
```

```
Given a CLI request with no x-web-user-email header
When any session-scoped route calls check_session_access(request, session_id)
Then the function returns immediately on the no-email branch
And the request is allowed (CLI auth is handled by verify_caller, not by this function)
```

```
Given a web user with email owner@instrukt.ai and role member
And a session 81f0a35e-58c4-4d36-9d2b-2e0f9a0c711b whose human_email is owner@instrukt.ai
When DELETE /sessions/81f0a35e-58c4-4d36-9d2b-2e0f9a0c711b runs
Then check_session_access(request, "81f0a35e-58c4-4d36-9d2b-2e0f9a0c711b", require_owner=True) returns
And the session is closed
```

```
Given a web user with email teammate@instrukt.ai and role member
And a session 81f0a35e-58c4-4d36-9d2b-2e0f9a0c711b owned by owner@instrukt.ai
When DELETE /sessions/81f0a35e-58c4-4d36-9d2b-2e0f9a0c711b runs
Then check_session_access raises HTTPException 403 "Forbidden: not session owner"
And the session is not closed
```

```
Given a web user with email teammate@instrukt.ai and role member
And a session b9032d3e-2a4f-4c2e-9d10-c4e8b7e5f7a1 owned by owner@instrukt.ai with visibility "shared"
When POST /sessions/b9032d3e-2a4f-4c2e-9d10-c4e8b7e5f7a1/message runs
Then check_session_access returns on the member+shared branch
And the message is dispatched
```

```
Given a web user with email teammate@instrukt.ai and role member
And a session b9032d3e-2a4f-4c2e-9d10-c4e8b7e5f7a1 owned by owner@instrukt.ai with visibility "private"
When POST /sessions/b9032d3e-2a4f-4c2e-9d10-c4e8b7e5f7a1/message runs
Then check_session_access raises HTTPException 403 "Forbidden: no access to this session"
```

```
Given a web user with email customer@example.com and role customer
And a session b9032d3e-2a4f-4c2e-9d10-c4e8b7e5f7a1 owned by owner@instrukt.ai with visibility "shared"
When POST /sessions/b9032d3e-2a4f-4c2e-9d10-c4e8b7e5f7a1/message runs
Then check_session_access raises HTTPException 403 "Forbidden: no access to this session"
Because the shared-visibility unlock only applies to members, not customers
```

```
Given any web user identity
And a session_id that does not exist in cache or database
When check_session_access(request, session_id) runs
Then check_session_access raises HTTPException 404 "Session not found"
```

### Implementation pointers (v1)

- Function: `teleclaude/api/session_access.py:12-61` (`check_session_access`)
- Admin role constant: `teleclaude/constants.py:51` (`HUMAN_ROLE_ADMIN = "admin"`)
- Member role constant: `teleclaude/constants.py:52` (`HUMAN_ROLE_MEMBER = "member"`)
- Session lookup: `teleclaude/api/auth.py` (`get_cached_session`) with `teleclaude/core/db.get_session` fallback
- Owner-required caller (delete): `teleclaude/api/sessions_routes.py:612`
- Standard callers (send / keys / voice / agent-restart / revive / tail / messages / stream):
  - `teleclaude/api/sessions_routes.py:931` (send message)
  - `teleclaude/api/sessions_routes.py:548` (get messages — `get_session_messages`)
  - `teleclaude/api/sessions_actions_routes.py:382` (keys)
  - `teleclaude/api/sessions_actions_routes.py:409` (voice)
  - `teleclaude/api/sessions_actions_routes.py:464` (agent-restart)
  - `teleclaude/api/sessions_actions_routes.py:504` (revive)
  - `teleclaude/api/streaming.py:365` (SSE stream)
- Companion list-level filter (separate code path, same rules): `teleclaude/api/sessions_routes.py:89-109` (`_filter_sessions_by_role`)
- Companion WebSocket filter (separate code path, same rules): `teleclaude/api/ws_mixin.py:253-265`

### Cross-context references

- The `human_email` and `visibility` columns are owned by `agent_runtime` (the `sessions` table). The `visibility` value is set by the session owner via a web action; identity reads it without writing. The `human_email` is stamped at session creation time by the session-creation pipeline.
- This feature is the per-session companion to the trust boundary: `feature/identity/identity-header-trust-boundary` decides whether the headers may even be read; this feature decides what they unlock once read.
- The check is separate from `feature/identity/caller-verification`. `verify_caller` decides WHO is calling (returning a `CallerIdentity` with `human_email` / `human_role`); `check_session_access` decides WHICH SESSIONS that who can touch.
- The list-level filter `_filter_sessions_by_role` (used by `GET /sessions` and the WebSocket `sessions` data type) implements the same owner-or-shared rule for collections. The single-session function and the list filter must stay in sync — any divergence is a security defect.
- In v2 this collapses into a uniform policy table over an `AccessGrant` aggregate; see the v2 identity domain spec.

## Known caveats

- The "no identity headers = TUI/tool client" branch is correct only because the trust boundary upstream prevents arbitrary callers from supplying the headers. If the trust boundary regresses, this check silently degrades to "anyone who omits the header gets through."
- A web user with the `contributor` or `newcomer` role gets neither the admin bypass nor the member+shared unlock — only ownership grants access. v1 has no documented use case for these roles on the web interface; they fall through to 403.
- The `visibility` attribute is read with `getattr(session, "visibility", "private")` — a session record missing the attribute is treated as `private`. This is fail-closed.
- Owner check uses exact string equality on `human_email`. Email casing is not normalized at this layer; the column value is whatever was stamped at session-creation time. If the same human is registered with one casing and a session was stamped with another, the check would deny access. In practice all stamping paths normalize, but this is not enforced at the access-check layer.
- The 404 path leaks session-existence information through the status code: an unauthorized caller can distinguish "session does not exist" (404) from "session exists but you cannot access it" (403). v1 accepts this trade-off; v2 may collapse both to 404.
- The function reaches into the database on every call (after a cache miss). On hot paths (streaming, message-listing) the cache hit rate determines whether this becomes a per-request DB read.
