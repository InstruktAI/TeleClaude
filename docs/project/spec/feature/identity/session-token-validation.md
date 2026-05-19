---
id: project/spec/feature/identity/session-token-validation
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Validate an inbound x-session-token at the daemon's HTTP boundary, returning a CallerIdentity carrying the bound principal and role.
---

# Session Token Validation — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 rule for turning an inbound `x-session-token` header into a verified `CallerIdentity`. The token path takes priority over the dual-factor `x-caller-session-id` path so daemon-spawned agent sessions can authenticate even when no `human_role` is present. Validation has two layers: a ledger lookup (cached for 30 s) that produces the `SessionToken` row, and a defense-in-depth check against the owning `Session`'s lifecycle that rejects tokens whose session is closing or closed regardless of what the ledger says. The result is a `CallerIdentity` carrying the session id, the principal and role from the token, and the live system/human role derived from the session record.

## Canonical fields

### Use cases

```
Given an inbound request carrying x-session-token: <uuid>
When verify_caller runs
Then the token path is taken in preference to the dual-factor path
And _verify_token_identity resolves the SessionToken row from the ledger
And a CallerIdentity is returned with session_id, principal, principal_role, system_role, human_role
```

```
Given a token already resolved within the past 30 seconds
When _verify_token_identity is called again with the same token
Then the cached SessionToken row is returned without a DB hit
And the owning session is then loaded (also cached for 30 s) to re-check lifecycle
```

```
Given an x-session-token that does not exist in the ledger
When _verify_token_identity is called
Then HTTPException(401, "invalid or expired session token") is raised
```

```
Given a valid x-session-token whose owning session has closed_at set
When _verify_token_identity is called
Then HTTPException(401, "session no longer active") is raised
And the rejection happens even if the ledger row was not yet revoked
```

```
Given a valid x-session-token whose owning session lifecycle_status is "closed" or "closing"
When _verify_token_identity is called
Then HTTPException(401, "session no longer active") is raised
And this is the defense-in-depth barrier that catches revoke-on-close races
```

```
Given a token-authenticated CallerIdentity reaches a tool clearance gate
When require_clearance evaluates the caller
Then the principal_role substitutes for human_role when human_role is None
And clearance is granted or denied based on the (system_role, human_role-or-principal_role) pair
```

### Implementation pointers (v1)

- Header dispatch: `teleclaude/api/auth.py:256-293` (`verify_caller`)
- Token path resolver: `teleclaude/api/auth.py:172-195` (`_verify_token_identity`)
- Ledger lookup: `teleclaude/core/db/_tokens.py:38-47` (`validate_session_token`)
- Token cache: `teleclaude/api/auth.py:46-107` (`_TOKEN_CACHE_TTL=30s`, max 256, `_get_cached_token`, `_put_cached_token`, `invalidate_token_cache`)
- Session cache: `teleclaude/api/auth.py:42-80` (`_SESSION_CACHE_TTL=30s`, max 256)
- Verified session loader: `teleclaude/api/auth.py:161-169` (`_get_verified_session`)
- Defense-in-depth lifecycle check: `teleclaude/api/auth.py:183-187`
- System-role derivation: `teleclaude/api/auth.py:130-145` (`_derive_session_system_role`)
- Clearance fallback to principal_role: `teleclaude/api/auth.py:296-301` (`_is_tool_denied`)

### Cross-context references

- Consumed by every API route that depends on `verify_caller` (every `clearance_*` factory in `teleclaude/api/auth.py:361-390`).
- Depends on `agent_runtime` session lifecycle columns (`closed_at`, `lifecycle_status`) for the defense-in-depth check.
- Pairs with `feature/identity/session-token-revocation`: the cache invalidations at session close coordinate with this path so a revoked token surfaces immediately rather than after the cache TTL.
- No v1 domain event is emitted on validation success or failure. In v2 this corresponds to `identity.resolve(headers)` returning a `Principal` aggregate.

## Known caveats

- Cache TTL is 30 s for both the token row and the session record. A token revoked between cache load and TTL expiry is still caught: the session record is reloaded on every token-path call, and the defense-in-depth lifecycle check reads the freshly-cached session — the revoker explicitly invalidates the session cache after the DB write to make this work (see `feature/identity/session-token-revocation`).
- A 401 with the literal string `"invalid or expired session token"` covers both "never existed" and "was revoked" — the wording is deliberately ambiguous. There is no separate code path for an expired-but-known token because tokens have no expiry.
- The principal_role on a `CallerIdentity` reflects the role stamped at issuance time, not the live session's role. Clearance gates that read `principal_role` (the human_role fallback) trust the stamp; gates that read `system_role` trust the live session via `_derive_session_system_role`.
- Cache eviction is age-based ("oldest entry"), not LRU — a stable working set above 256 entries can thrash, but that is far beyond realistic concurrent agent counts.
- The token path is taken whenever `x-session-token` is present, even if `x-caller-session-id` is also present. The dual-factor path is reached only when no token header is supplied. This is intentional: agents always have a token; humans never do.
