---
description: 'Validate an inbound session-token signal at the identity context''s boundary, returning a CallerIdentity carrying the bound principal and role.'
visibility: 'public'
---

# Session Token Validation — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 rule for turning an inbound session-token signal into a verified `CallerIdentity`. The token path takes priority over the dual-factor caller-session-id path so identity-context-spawned agent sessions can authenticate even when no `human_role` is present. Validation has two layers: a ledger lookup (cached with a short TTL) that produces the bound `(principal, role)`, and a defense-in-depth check against the owning session's lifecycle that rejects tokens whose session is closing or closed regardless of what the ledger says. The result is a `CallerIdentity` carrying the session id, the principal and role from the token, and the live system/human role derived from the session record.

## Canonical fields

### Use cases

```
Given an inbound call carrying a session-token signal `<uuid>`
When caller verification runs
Then the token path is taken in preference to the dual-factor path
And token validation resolves the ledger entry
And a CallerIdentity is returned with session_id, principal, principal_role, system_role, human_role
```

```
Given a token already resolved within the cache TTL
When token validation is invoked again with the same token
Then the cached ledger entry is returned without a store hit
And the owning session is then loaded (also cached for the same TTL) to re-check lifecycle
```

```
Given a session-token that does not exist in the ledger
When token validation runs
Then the call is rejected as "invalid or expired session token"
```

```
Given a valid session-token whose owning session has closed_at set
When token validation runs
Then the call is rejected as "session no longer active"
And the rejection happens even if the ledger entry was not yet revoked
```

```
Given a valid session-token whose owning session lifecycle_status is "closed" or "closing"
When token validation runs
Then the call is rejected as "session no longer active"
And this is the defense-in-depth barrier that catches revoke-on-close races
```

```
Given a token-authenticated CallerIdentity reaches a clearance gate
When command clearance evaluates the caller
Then the principal_role substitutes for human_role when human_role is None
And clearance is granted or denied based on the (system_role, human_role-or-principal_role) pair
```

### Cross-context references

- Consumed by every protected operation that depends on caller verification (every clearance gate in the identity context).
- Depends on `agent_runtime` session lifecycle state (`closed_at`, `lifecycle_status`) for the defense-in-depth check.
- Pairs with `feature/identity/session-token-revocation`: the cache invalidations at session close coordinate with this path so a revoked token surfaces immediately rather than after the cache TTL.
- No v1 domain event is emitted on validation success or failure. In v2 this corresponds to `identity.resolve(headers)` returning a `Principal` aggregate.

## Known caveats

- Cache TTL is short for both the token entry and the session record. A token revoked between cache load and TTL expiry is still caught: the session record is reloaded on every token-path call, and the defense-in-depth lifecycle check reads the freshly-cached session — the revoker explicitly invalidates the session cache after the lifecycle write to make this work (see `feature/identity/session-token-revocation`).
- The rejection message "invalid or expired session token" covers both "never existed" and "was revoked" — the wording is deliberately ambiguous. There is no separate code path for an expired-but-known token because tokens have no expiry.
- The principal_role on a `CallerIdentity` reflects the role stamped at issuance time, not the live session's role. Clearance gates that read `principal_role` (the human_role fallback) trust the stamp; gates that read `system_role` trust the live session via the system-role derivation in caller verification.
- Cache eviction is age-based ("oldest entry"), not LRU — a stable working set above the cache cap can thrash, but that is far beyond realistic concurrent agent counts.
- The token path is taken whenever the session-token signal is present, even if the caller-session-id signal is also present. The dual-factor path is reached only when no token signal is supplied. This is intentional: agents always have a token; humans never do.
