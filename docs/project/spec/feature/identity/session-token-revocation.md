---
id: 'project/spec/feature/identity/session-token-revocation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Remove a session''s tokens from the ledger and invalidate auth caches early in the termination path so in-flight calls are rejected immediately.'
---

# Session Token Revocation — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 rule for retiring a session's credentials when the session terminates. Revocation runs early inside the session-termination path — before tmux is killed, before the lifecycle flips to `closing`, before any other cleanup — so any CLI call already in flight with the doomed token is rejected at the next identity-context hop. The revocation itself is a hard deletion of every session-token ledger entry for the session_id (there is no `revoked_at` soft-delete column), followed by token-cache invalidation to drop stale entries, and then session-cache invalidation after the lifecycle write so the defense-in-depth lifecycle check in token validation reads `closing`/`closed` on the next miss. Revocation is best-effort: a thrown error is logged and termination proceeds anyway, because the defense-in-depth check is the safety net.

## Canonical fields

### Use cases

```
Given a session_id reaching the termination path for any reason
When the termination sequence begins
Then session-token revocation is invoked BEFORE tmux is killed
And BEFORE lifecycle_status is flipped to "closing"
And every ledger entry matching that session_id is deleted
```

```
Given revocation has just deleted the ledger entries
When termination continues
Then token-cache invalidation drops all cached token entries whose session_id matches
And after the lifecycle write, session-cache invalidation drops the stale session
And the next inbound call with the old token misses both caches and re-reads fresh state
```

```
Given an in-flight CLI call carrying a token for a session that just revoked
When the call reaches token validation after the deletion
Then the ledger lookup misses
And the call is rejected as "invalid or expired session token"
```

```
Given a race where the in-flight call's token entry was already cached
When the call reaches token validation before token-cache invalidation runs
Then the cached token entry still passes the ledger check
And the session lookup loads (or re-uses cache for) the owning session
And the defense-in-depth check sees closed_at or lifecycle_status ∈ {"closed","closing"}
And the call is rejected as "session no longer active"
```

```
Given the revocation step itself throws an error
When the termination path runs
Then the error is caught and logged
And termination continues without aborting
And the defense-in-depth lifecycle check still rejects any surviving cached tokens
```

### Cross-context references

- Triggered by `agent_runtime` session termination.
- Pairs with `feature/identity/session-token-validation`: the cache invalidations and the lifecycle-state defense-in-depth check are the two halves of the revocation barrier.
- Backstopped by `feature/identity/orphan-session-token-cleanup`: tokens that survive a best-effort revocation failure are swept by the periodic orphan cleanup.
- No v1 domain event is emitted on revocation. In v2 this emits `identity.token.revoked` carrying `revoke_reason: session_ended`.

## Known caveats

- Revocation is a hard deletion. There is no audit trail of revoked tokens at the ledger level; the audit lives in the session lifecycle state (`closed_at`, `lifecycle_status`).
- Revocation is best-effort: the termination path swallows errors from revocation and proceeds. The defense-in-depth lifecycle check in token validation is the safety net that prevents a logged revocation failure from leaving tokens live.
- The ordering — revoke tokens → flip lifecycle → invalidate session cache → kill tmux — is significant. Invalidating the session cache AFTER the lifecycle write ensures the next auth cache miss reads the fresh `closing` state. Doing it before the write would race: a refilled cache could still hold the pre-close session record.
- The token cache invalidation walks every entry comparing `session_id` (O(n)). With the current cache cap this is irrelevant; it does mean the cost scales with cache size if the cap is ever raised.
- A session that is force-removed from the session store (rather than terminated) bypasses this path entirely. Its tokens become orphans and are picked up only by the periodic orphan-cleanup sweep.
