---
description: "Remove a session's tokens from the ledger early in the termination path."
visibility: 'public'
---

# Session Token Revocation — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 rule for retiring a session's tokens when the session terminates. Revocation runs early inside the session-termination path — before tmux is killed, before the lifecycle flips to `closing`, before any other cleanup. The revocation itself is a hard deletion of every session-token ledger entry for the session_id (there is no `revoked_at` soft-delete column). No request surface validates a session token (`feature/identity/session-token-validation`), so revocation keeps the ledger in step with the sessions that are open; it gates no call. Revocation is best-effort: a thrown error is logged and termination proceeds anyway.

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
Given the revocation step itself throws an error
When the termination path runs
Then the error is caught and logged
And termination continues without aborting
```

### Cross-context references

- Triggered by `agent_runtime` session termination.
- Backstopped by `feature/identity/orphan-session-token-cleanup`: tokens that survive a best-effort revocation failure are swept by the periodic orphan cleanup.
- No v1 domain event is emitted on revocation. In v2 this emits `identity.token.revoked` carrying `revoke_reason: session_ended`.

## Known caveats

- Revocation is a hard deletion. There is no audit trail of revoked tokens at the ledger level; the audit lives in the session lifecycle state (`closed_at`, `lifecycle_status`).
- A session that is force-removed from the session store (rather than terminated) bypasses this path entirely. Its tokens become orphans and are picked up only by the periodic orphan-cleanup sweep.
