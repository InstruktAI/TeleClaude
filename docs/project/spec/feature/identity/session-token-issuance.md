---
id: project/spec/feature/identity/session-token-issuance
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Issue a v1 session token at bootstrap for system-principal sessions and write it into the session's TMPDIR identity file.
---

# Session Token Issuance — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 rule for minting a session token at the start of a session's life. A session token is a UUID4 string stored in the `session_tokens` ledger that binds a session to a `(principal, role)` pair resolved at bootstrap time. Tokens are issued **only** for sessions whose resolved principal is `system:*` — the daemon-spawned agent sessions that have no human behind them. Human-principal sessions never receive a token; they authenticate via terminal-email and the dual-factor caller-session-id path instead. The plaintext token is returned by the DB layer exactly once and written into the session's TMPDIR identity file, where CLI tools running inside the session read it and present it on every daemon call.

## Canonical fields

### Use cases

```
Given a session whose resolved principal is "system:<session_id>"
When ensure_tmux_with_identity bootstraps the session
Then db.issue_session_token(session_id, principal, role) generates a UUID4
And a SessionToken row (token, session_id, principal, role) is inserted in the ledger
And the plaintext token is written into the session's TMPDIR identity file
```

```
Given a session whose resolved principal is "human:<email>"
When ensure_tmux_with_identity bootstraps the session
Then no SessionToken row is created
And the identity file is written with session_token=None
And the session must authenticate via x-telec-email and x-caller-session-id headers
```

```
Given a child worker session inheriting "system:<parent-session-id>" as its principal
When ensure_tmux_with_identity bootstraps the child
Then a NEW SessionToken row is issued for the child's session_id
And the row's principal column is the inherited "system:<parent-session-id>" value
And the row's role column carries the role returned by resolve_session_principal
```

```
Given a freshly issued session token
When the session bootstrap completes
Then the token is bound for the lifetime of the session
And has no expiry, no rotation, and no time-based revocation
And lives until revoke_session_tokens is called at session close
```

### Implementation pointers (v1)

- Issuance function: `teleclaude/core/db/_tokens.py:21-36` (`issue_session_token`)
- Bootstrap call site: `teleclaude/core/session_bootstrap.py:41-44` (system-principal gate)
- Identity file writer: `teleclaude/session_identity.py:104-117` (`write_session_identity_to`)
- Ledger table: `teleclaude/core/db_models.py:327-336` (`SessionToken`)
- Principal resolution: `teleclaude/core/db/_sync.py:166-192` (`resolve_session_principal`)
- TMPDIR consumer (sync CLI): `teleclaude/cli/tool_client.py:60-100`
- TMPDIR consumer (async CLI): `teleclaude/cli/api_client.py:468-490`

### Cross-context references

- Producer: `identity` (this snippet).
- Consumers: CLI tools running inside the session read the token from the TMPDIR identity file and inject it as the `x-session-token` header on every daemon call. See `feature/identity/session-token-validation`.
- Depends on `feature/identity/principal-resolution` for the `(principal, role)` pair stamped onto the ledger row.
- No v1 domain event is emitted by issuance. In v2 this path emits `identity.token.issued` with CLUSTER visibility under a commit-then-emit pattern.

## Known caveats

- The plaintext token is returned from `issue_session_token` exactly once and immediately written to disk in the session's TMPDIR. There is no secondary retrieval path — losing the identity file orphans the session from its own credential until the next bootstrap.
- The `role` column on a ledger row reflects the role returned by `resolve_session_principal`, which for an inherited `system:` principal is the fallback `customer` band unless the child carries an explicit `human_role`. Token-path validation re-derives the authoritative system role from the live session record (`_derive_session_system_role`) rather than trusting the ledger's `role` column for clearance decisions.
- Issuance is gated strictly on the literal `principal.startswith("system:")` check. Any future principal namespace (e.g. `service:`) would silently bypass token issuance until the gate is widened.
- There is no expiry timer, no rotation hook, and no idle-revocation. A long-lived session retains the same token until its `revoke_session_tokens` call at close. This is intentional: token lifetime tracks session lifetime exactly.
- The daemon writes the identity file into the session's TMPDIR without mutating its own environment, so the daemon process cannot accidentally authenticate as one of its child sessions.
