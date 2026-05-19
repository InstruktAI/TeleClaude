---
id: project/spec/feature/identity/session-token-revocation
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Delete a session's tokens from the ledger and invalidate auth caches early in the termination path so in-flight calls are rejected immediately.
---

# Session Token Revocation — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 rule for retiring a session's credentials when the session terminates. Revocation runs early inside `_terminate_session_inner` — before tmux is killed, before the lifecycle flips to `closing`, before any other cleanup — so any CLI call already in flight with the doomed token is rejected at the next daemon hop. The revocation itself is a hard DELETE of every `SessionToken` row for the session_id (there is no `revoked_at` soft-delete column), followed by `invalidate_token_cache(session_id)` to drop stale cache entries, and then `invalidate_session_cache(session_id)` after the lifecycle DB write so the defense-in-depth lifecycle check in `_verify_token_identity` reads `closing`/`closed` on the next miss. Revocation is best-effort: a thrown exception is logged and termination proceeds anyway, because the defense-in-depth check is the safety net.

## Canonical fields

### Use cases

```
Given a session_id reaching _terminate_session_inner for any reason
When the termination sequence begins
Then db.revoke_session_tokens(session_id) is called BEFORE tmux is killed
And BEFORE lifecycle_status is flipped to "closing"
And every SessionToken row matching that session_id is DELETED from the ledger
```

```
Given revocation has just deleted the ledger rows
When termination continues
Then invalidate_token_cache(session_id) drops all cached token rows whose session_id matches
And after the lifecycle_status DB write, invalidate_session_cache(session_id) drops the stale session
And the next inbound call with the old token misses both caches and re-reads fresh state
```

```
Given an in-flight CLI call carrying a token for a session that just revoked
When the call reaches _verify_token_identity after the DELETE
Then the ledger lookup misses
And HTTPException(401, "invalid or expired session token") is raised
```

```
Given a race where the in-flight call's token row was already cached
When the call reaches _verify_token_identity before invalidate_token_cache runs
Then the cached token row still passes the ledger check
And the session lookup loads (or re-uses cache for) the owning Session
And the defense-in-depth check sees closed_at or lifecycle_status ∈ {"closed","closing"}
And HTTPException(401, "session no longer active") is raised
```

```
Given revoke_session_tokens itself throws an exception
When _terminate_session_inner runs
Then the exception is caught and logged
And termination continues without aborting
And the defense-in-depth lifecycle check still rejects any surviving cached tokens
```

### Implementation pointers (v1)

- Revocation function: `teleclaude/core/db/_tokens.py:49-56` (`revoke_session_tokens`)
- Termination call site: `teleclaude/core/session_cleanup.py:281-295`
- Token cache invalidator: `teleclaude/api/auth.py:103-107` (`invalidate_token_cache`)
- Session cache invalidator: `teleclaude/api/auth.py:78-80` (`invalidate_session_cache`)
- Defense-in-depth lifecycle check: `teleclaude/api/auth.py:183-187`
- Lifecycle flip following revocation: `teleclaude/core/session_cleanup.py:288-289`

### Cross-context references

- Triggered by `agent_runtime` session termination (`_terminate_session_inner`).
- Pairs with `feature/identity/session-token-validation`: the cache invalidations and the lifecycle-state defense-in-depth check are the two halves of the revocation barrier.
- Backstopped by `feature/identity/orphan-session-token-cleanup`: tokens that survive a best-effort revocation failure are swept by the periodic orphan cleanup.
- No v1 domain event is emitted on revocation. In v2 this emits `identity.token.revoked` carrying `revoke_reason: session_ended`.

## Known caveats

- Revocation is a hard DELETE. There is no audit trail of revoked tokens at the ledger level; the audit lives in the session lifecycle record (`closed_at`, `lifecycle_status`).
- Revocation is best-effort: `_terminate_session_inner` swallows exceptions from `revoke_session_tokens` and proceeds with termination. The defense-in-depth lifecycle check in `_verify_token_identity` is the safety net that prevents a logged revocation failure from leaving tokens live.
- The ordering — revoke tokens → flip lifecycle → invalidate session cache → kill tmux — is significant. Invalidating the session cache AFTER the lifecycle write ensures the next auth cache miss reads the fresh `closing` state. Doing it before the write would race: a refilled cache could still hold the pre-close session record.
- The token cache invalidation walks every entry comparing `session_id` (O(n)). With a 256-entry cap this is irrelevant; it does mean the cost scales with cache size if the cap is ever raised.
- A session that is force-deleted from the DB (rather than terminated) bypasses this path entirely. Its tokens become orphans and are picked up only by `cleanup_orphan_session_tokens`.
