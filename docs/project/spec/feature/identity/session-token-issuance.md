---
id: 'project/spec/feature/identity/session-token-issuance'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Issue a v1 session token at bootstrap for system-principal sessions and write it into the session''s TMPDIR identity file.'
---

# Session Token Issuance — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 rule for minting a session token at the start of a session's life. A session token is a UUID4 string stored in the session-token ledger that binds a session to a `(principal, role)` pair resolved at bootstrap time. Tokens are issued **only** for sessions whose resolved principal is `system:*` — the identity-context-spawned agent sessions that have no human behind them. Human-principal sessions never receive a token; they authenticate via the terminal-email signal and the dual-factor caller-session-id path instead. The plaintext token is returned by the token-issuance capability exactly once and written into the session's TMPDIR identity file, where CLI tools running inside the session read it and present it on every call into the identity context.

## Canonical fields

### Use cases

```
Given a session whose resolved principal is "system:<session_id>"
When the session is bootstrapped
Then session-token issuance generates a UUID4
And a ledger entry binding (token, session_id, principal, role) is recorded
And the plaintext token is written into the session's TMPDIR identity file
```

```
Given a session whose resolved principal is "human:<email>"
When the session is bootstrapped
Then no ledger entry is created
And the identity file is written with session_token=None
And the session must authenticate via the terminal-email and caller-session-id signals
```

```
Given a child worker session inheriting "system:<parent-session-id>" as its principal
When the child is bootstrapped
Then a NEW ledger entry is issued for the child's session_id
And the entry's principal is the inherited "system:<parent-session-id>" value
And the entry's role carries the role returned by principal resolution
```

```
Given a freshly issued session token
When the session bootstrap completes
Then the token is bound for the lifetime of the session
And has no expiry, no rotation, and no time-based revocation
And lives until token revocation is invoked at session close
```

### Cross-context references

- Producer: the identity context (this snippet).
- Consumers: CLI tools running inside the session read the token from the TMPDIR identity file and inject it as the session-token signal on every call into the identity context. See `feature/identity/session-token-validation`.
- Depends on `feature/identity/principal-resolution` for the `(principal, role)` pair stamped onto the ledger entry.
- No v1 domain event is emitted by issuance. In v2 this path emits `identity.token.issued` with CLUSTER visibility under a commit-then-emit pattern.

## Known caveats

- The plaintext token is returned from the issuance capability exactly once and immediately written to disk in the session's TMPDIR. There is no secondary retrieval path — losing the identity file orphans the session from its own credential until the next bootstrap.
- The `role` value on a ledger entry reflects the role returned by principal resolution, which for an inherited `system:` principal is the fallback `customer` band unless the child carries an explicit `human_role`. Token-path validation re-derives the authoritative system role from the live session record rather than trusting the ledger's `role` value for clearance decisions.
- Issuance is gated strictly on the literal `principal.startswith("system:")` check. Any future principal namespace (e.g. `service:`) would silently bypass token issuance until the gate is widened.
- There is no expiry timer, no rotation hook, and no idle-revocation. A long-lived session retains the same token until its revocation call at close. This is intentional: token lifetime tracks session lifetime exactly.
- The identity context writes the file into the session's TMPDIR without mutating its own environment, so the identity-context process cannot accidentally authenticate as one of its child sessions.
