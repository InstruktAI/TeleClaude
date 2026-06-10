---
description: 'Authorize web-frontend session-scoped operations against the session owner, the session''s shared/private visibility, and the caller''s role.'
visibility: 'public'
---

# Session Access & Visibility — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The per-session authorization rule for web-frontend callers. Once the trust boundary admits a call carrying the web-user email / role signals, every operation that targets a specific session calls the session-access check before doing any work. The check decides three things in one pass: does this session exist, may this web user see it, and — for owner-only operations — may this web user end it. Owner-only operations (currently session deletion) require either the session's owner email or the admin role. Standard operations (read messages, send a message, send keys/voice, restart the agent, revive, tail the transcript, stream) allow the owner, an admin, OR any member-role caller when the owner has flipped the session's `visibility` to `shared`. CLI / tool / agent callers that arrive without identity signals bypass the check entirely — they are already gated by caller verification's session-token and terminal-email paths. The `shared` visibility flag is the cooperation primitive: it is the owner's explicit "this session is okay for my teammates to read and act on" — without that flag, every session is private to its owner.

## Canonical fields

### Use cases

```
Given a web user with email maurice@instrukt.ai and role admin
And a session 7c6a1f80-e4d1-4d24-bf12-3a1b9d2e0e44 owned by anyone
When any session-scoped operation invokes the session-access check
Then the check returns immediately on the admin-bypass branch
And the operation proceeds
```

```
Given a CLI call with no web-user email signal
When any session-scoped operation invokes the session-access check
Then the check returns immediately on the no-email branch
And the call is allowed (CLI auth is handled by caller verification, not by this check)
```

```
Given a web user with email owner@instrukt.ai and role member
And a session 81f0a35e-58c4-4d36-9d2b-2e0f9a0c711b whose human_email is owner@instrukt.ai
When the owner issues a session-delete operation against that session
Then the session-access check (owner-required) accepts the call
And the session is closed
```

```
Given a web user with email teammate@instrukt.ai and role member
And a session 81f0a35e-58c4-4d36-9d2b-2e0f9a0c711b owned by owner@instrukt.ai
When the teammate issues a session-delete operation
Then the session-access check rejects the call as "Forbidden: not session owner"
And the session is not closed
```

```
Given a web user with email teammate@instrukt.ai and role member
And a session b9032d3e-2a4f-4c2e-9d10-c4e8b7e5f7a1 owned by owner@instrukt.ai with visibility "shared"
When the teammate issues a send-message operation
Then the session-access check returns on the member+shared branch
And the message is dispatched
```

```
Given a web user with email teammate@instrukt.ai and role member
And a session b9032d3e-2a4f-4c2e-9d10-c4e8b7e5f7a1 owned by owner@instrukt.ai with visibility "private"
When the teammate issues a send-message operation
Then the session-access check rejects the call as "Forbidden: no access to this session"
```

```
Given a web user with email customer@example.com and role customer
And a session b9032d3e-2a4f-4c2e-9d10-c4e8b7e5f7a1 owned by owner@instrukt.ai with visibility "shared"
When the customer issues a send-message operation
Then the session-access check rejects the call as "Forbidden: no access to this session"
Because the shared-visibility unlock only applies to members, not customers
```

```
Given any web user identity
And a session_id that does not exist in cache or session store
When the session-access check runs
Then the check raises a session-not-found error
```

### Cross-context references

- The `human_email` and `visibility` columns are owned by `agent_runtime` (the session store). The `visibility` value is set by the session owner via a web action; the identity context reads it without writing. The `human_email` is stamped at session creation time by the session-creation pipeline.
- This feature is the per-session companion to the trust boundary: `feature/identity/identity-header-trust-boundary` decides whether the identity signals may even be read; this feature decides what they unlock once read.
- The check is separate from `feature/identity/caller-verification`. Caller verification decides WHO is calling (returning a `CallerIdentity` with `human_email` / `human_role`); session-access decides WHICH SESSIONS that who can touch.
- The list-level filter implements the same owner-or-shared rule for collections and is consumed by the session-list operation and the streaming `sessions` data type. The single-session check and the list filter must stay in sync — any divergence is a security defect.
- In v2 this collapses into a uniform policy table over an `AccessGrant` aggregate; see the v2 identity domain spec.

## Known caveats

- The "no identity signals = TUI/tool client" branch is correct only because the trust boundary upstream prevents arbitrary callers from supplying the signals. If the trust boundary regresses, this check silently degrades to "anyone who omits the signal gets through."
- A web user with the `contributor` or `newcomer` role gets neither the admin bypass nor the member+shared unlock — only ownership grants access. v1 has no documented use case for these roles on the web interface; they fall through to a forbidden response.
- The `visibility` attribute is read defensively — a session record missing the attribute is treated as `private`. This is fail-closed.
- The owner check uses exact string equality on `human_email`. Email casing is not normalized at this layer; the column value is whatever was stamped at session-creation time. If the same human is registered with one casing and a session was stamped with another, the check would deny access. In practice all stamping paths normalize, but this is not enforced at the access-check layer.
- The not-found path leaks session-existence information through the error type: an unauthorized caller can distinguish "session does not exist" from "session exists but you cannot access it." v1 accepts this trade-off; v2 may collapse both to not-found.
- The check reaches into the session store on every call (after a cache miss). On hot paths (streaming, message-listing) the cache hit rate determines whether this becomes a per-call store read.
