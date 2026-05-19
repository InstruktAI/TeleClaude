---
id: project/spec/feature/identity/orphan-session-token-cleanup
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Periodic maintenance sweep that deletes session_tokens rows whose owning session is closed or no longer present.
---

# Orphan Session Token Cleanup — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 backstop that keeps the `session_tokens` ledger from accumulating dead rows. The `MaintenanceService` periodic loop calls `cleanup_orphan_session_tokens` every hour alongside other maintenance sweeps (orphan tmux sessions, workspaces, tmpdirs, terminal operations, etc.). The query selects all `Session` rows considered "live" — `closed_at IS NULL` AND (`lifecycle_status IS NULL` OR `lifecycle_status != "closed"`) — and deletes every `SessionToken` whose `session_id` is not in that set. This is a safety net, not the primary revocation path: tokens for terminated sessions are normally deleted synchronously by `revoke_session_tokens` (see `feature/identity/session-token-revocation`). Orphan cleanup catches the residue from best-effort revocation failures and from sessions deleted directly from the DB without going through the termination path.

## Canonical fields

### Use cases

```
Given a session that terminated cleanly via _terminate_session_inner
When the periodic maintenance loop runs an hour later
Then cleanup_orphan_session_tokens finds no rows to delete for that session
And returns rowcount=0 for that session's contribution to the sweep
```

```
Given a session whose revoke_session_tokens call raised an exception during termination
When the periodic maintenance loop runs next
Then the session is no longer "live" (closed_at is set or lifecycle_status == "closed")
And every SessionToken row for that session is deleted by the orphan sweep
And the returned rowcount reflects the deletions for logging
```

```
Given a session record that was removed from the Session table directly
When the periodic maintenance loop runs next
Then the orphaned SessionToken rows (no matching session_id in the live set) are deleted
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
When cleanup_orphan_session_tokens returns
Then rowcount of deleted tokens is available to the caller
And the loop continues to the next maintenance task (orphan session listeners, etc.)
```

### Implementation pointers (v1)

- Cleanup function: `teleclaude/core/db/_tokens.py:58-71` (`cleanup_orphan_session_tokens`)
- Live-session filter: `teleclaude/core/db/_tokens.py:60-66` (`closed_at IS NULL` AND `lifecycle_status IS NULL` OR `!= "closed"`)
- Periodic loop call site: `teleclaude/services/maintenance_service.py:77`
- Loop cadence and sibling sweeps: `teleclaude/services/maintenance_service.py:55-94` (1-hour sleep, sequential cleanups)
- Primary revocation path (the path this one backstops): `teleclaude/core/session_cleanup.py:281-286`

### Cross-context references

- Depends on `agent_runtime` session lifecycle columns (`closed_at`, `lifecycle_status`) to identify live sessions.
- Owned by the daemon's `MaintenanceService` runtime, running in the daemon process.
- Backstops `feature/identity/session-token-revocation`. The two paths together guarantee that no token outlives its session, regardless of failure mode.
- No v1 domain event is emitted by the sweep. In v2 the equivalent maintenance sweep emits `identity.token.revoked` with `revoke_reason: orphan_cleanup` for each row removed.

## Known caveats

- The sweep runs once per hour. A session whose synchronous revocation failed can therefore leave tokens in the ledger for up to one hour before the orphan sweep catches them — but the defense-in-depth lifecycle check in `_verify_token_identity` rejects any presented token in that window because the owning session is `closed` / `closing`. The ledger residue is harmless; the auth path is the actual barrier.
- The "live" filter treats `lifecycle_status IS NULL` as live. A session row created without a lifecycle_status (legacy or partially-initialized) and with `closed_at IS NULL` keeps its tokens. This is intentional: don't delete tokens for sessions whose state we cannot positively identify as closed.
- The deletion uses a single `DELETE ... WHERE session_id NOT IN (subquery)` statement; there is no per-row event emission or per-row logging. Only the aggregate `rowcount` is observable.
- The sweep is best-effort relative to concurrent revocations: a session that closes between the live-set subquery materialization and the DELETE execution could have its tokens deleted by both paths. The DELETE is idempotent so this is safe.
- Orphan cleanup is one of many maintenance sweeps in the same loop. A long-running earlier sweep can delay this one; the cadence is "approximately hourly," not "exactly hourly."
