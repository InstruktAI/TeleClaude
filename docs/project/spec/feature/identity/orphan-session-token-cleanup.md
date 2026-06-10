---
description: 'Periodic maintenance sweep that deletes session-token ledger entries whose owning session is closed or no longer present.'
visibility: 'public'
---

# Orphan Session Token Cleanup — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 backstop that keeps the session-token ledger from accumulating dead entries. The maintenance loop in the identity context runs an orphan-token sweep on a roughly hourly cadence alongside other maintenance sweeps (orphan tmux sessions, workspaces, tmpdirs, terminal operations, etc.). The sweep selects all session records considered "live" — `closed_at` unset AND (`lifecycle_status` unset OR not `"closed"`) — and deletes every session-token entry whose owning session is not in that set. This is a safety net, not the primary revocation path: tokens for terminated sessions are normally deleted synchronously by the revocation capability (see `feature/identity/session-token-revocation`). Orphan cleanup catches the residue from best-effort revocation failures and from sessions removed from the session store outside the termination path.

## Canonical fields

### Use cases

```
Given a session that terminated cleanly via the normal termination path
When the periodic maintenance loop runs an hour later
Then the orphan-token sweep finds no entries to delete for that session
And reports zero deletions for that session's contribution to the sweep
```

```
Given a session whose synchronous token revocation raised an error during termination
When the periodic maintenance loop runs next
Then the session is no longer "live" (closed_at is set or lifecycle_status == "closed")
And every session-token entry for that session is deleted by the orphan sweep
And the returned deletion count reflects those deletions for logging
```

```
Given a session record that was removed from the session store directly
When the periodic maintenance loop runs next
Then the orphaned session-token entries (no matching session in the live set) are deleted
And the ledger does not retain credentials whose owner no longer exists
```

```
Given a session in lifecycle_status "closing" (mid-termination)
When the periodic maintenance loop runs concurrently
Then the session is still considered NOT live (lifecycle_status != "closed" is the live test — "closing" matches "closed" semantically only via closed_at)
And the closed_at check is the authoritative filter for in-flight closes
```

```
Given the maintenance loop completes one iteration
When the orphan-token sweep returns
Then the deletion count is available to the caller
And the loop continues to the next maintenance task
```

### Cross-context references

- Depends on `agent_runtime` session lifecycle state (`closed_at`, `lifecycle_status`) to identify live sessions.
- Owned by the identity context's maintenance runtime.
- Backstops `feature/identity/session-token-revocation`. The two paths together guarantee that no token outlives its session, regardless of failure mode.
- No v1 domain event is emitted by the sweep. In v2 the equivalent maintenance sweep emits `identity.token.revoked` with `revoke_reason: orphan_cleanup` for each entry removed.

## Known caveats

- The sweep runs once per hour. A session whose synchronous revocation failed can therefore leave tokens in the ledger for up to one hour before the orphan sweep catches them — but the defense-in-depth lifecycle check in the token-validation path rejects any presented token in that window because the owning session is `closed` / `closing`. The ledger residue is harmless; the auth path is the actual barrier.
- The "live" filter treats `lifecycle_status` unset as live. A session record created without a lifecycle_status (legacy or partially-initialized) and with `closed_at` unset keeps its tokens. This is intentional: don't delete tokens for sessions whose state cannot be positively identified as closed.
- Deletion is a single bulk operation; there is no per-entry event emission or per-entry logging. Only the aggregate deletion count is observable.
- The sweep is best-effort relative to concurrent revocations: a session that closes between the live-set evaluation and the deletion could have its tokens deleted by both paths. The deletion is idempotent so this is safe.
- Orphan cleanup is one of many maintenance sweeps in the same loop. A long-running earlier sweep can delay this one; the cadence is "approximately hourly," not "exactly hourly."
