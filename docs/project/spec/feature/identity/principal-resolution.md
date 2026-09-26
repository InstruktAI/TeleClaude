---
description: 'Derive the canonical `(principal, role)` pair for a v1 session from its inherited principal, human email, or system role.'
visibility: 'public'
---

# Principal Resolution — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

<!-- planned-change:telec-startup-does-only-auth -->
The v1 rule for turning a session record into the `(principal, role)` pair that downstream authorization uses. Every authenticated CLI call into the identity context ultimately reaches a path that requires this resolution: tokens carry a `principal` stamped at issuance time, and that stamp is produced by this single capability. The capability answers "who is this session, and what authorization band does it carry?" with three deterministic rules — inherited principal wins, then human identity, then system identity — and raises a typed identity error when none apply.
<!-- change:telec-startup-does-only-auth -->
The v1 rule for turning a session record into the `(principal, role)` pair that downstream authorization uses. Every caller the client resolves from a session reaches this resolution: the principal the client carries on its requests is produced by this single capability. The capability answers "who is this session, and what authorization band does it carry?" with three deterministic rules — inherited principal wins, then human identity, then system identity — and raises a typed identity error when none apply.
<!-- /planned-change:telec-startup-does-only-auth -->

## Canonical fields

### Use cases

```
Given a session whose `principal` is already set (parent-inherited identity)
When principal resolution runs over the session
Then the inherited principal is returned verbatim
And the role is the session's human_role when present, else HUMAN_ROLE_CUSTOMER ("customer")
```

```
Given a session with human_email set and no inherited principal
When principal resolution runs over the session
Then principal is "human:<email>" using the session's human_email
And role is the session's human_role when present, else HUMAN_ROLE_CUSTOMER
```

```
Given a session with system_role set (no human_email, no inherited principal)
When principal resolution runs over the session
Then principal is "system:daemon" — the platform's own principal, the origin of all work with no human origin
And role is the session's system_role (e.g. "worker", "orchestrator", "integrator", "system")
```

```
Given a session with no principal, no human_email, and no system_role
When principal resolution runs over the session
Then a session-identity error is raised with a diagnostic naming the session_id
And the identity context surfaces this as an authentication-required failure
```

```
Given a child session started by a session whose principal is "system:daemon"
When principal resolution runs over the child
Then the child's principal is "system:daemon"
And every session with no human origin shares that one principal, distinguished by its own session id
```

### Cross-context references

<!-- planned-change:telec-startup-does-only-auth -->
- Consumer: `agent_runtime` session bootstrap calls this capability to decide whether to issue a session token (system-principal sessions only).
- The returned `principal` value is stamped into the session-token ledger entry at issuance, and read back by caller verification on the token path — see `project/spec/identity-and-auth` §3 and `feature/identity/caller-verification`.
<!-- change:telec-startup-does-only-auth -->
- Consumer: the client-side caller resolution (`project/spec/identity-and-auth` §6) resolves a session caller's principal through this capability.
<!-- /planned-change:telec-startup-does-only-auth -->
- No domain events are emitted by this capability directly. In v2 it corresponds to the materialization of a `Principal` aggregate, which DOES emit `identity.principal.created` on first issuance.

## Known caveats

<!-- planned-change:telec-startup-does-only-auth -->
- The capability returns `role`, but the contract notes it is "informational only — system sessions get their authoritative role from session.system_role, not from this capability." In practice the returned role is only used as the token's `role` value at issuance time; the v2 model collapses this ambiguity.
<!-- change:telec-startup-does-only-auth -->
- The capability returns `role`, but the contract notes it is "informational only — system sessions get their authoritative role from session.system_role, not from this capability." No consumer reads the returned role for a system principal; the v2 model collapses this ambiguity.
<!-- /planned-change:telec-startup-does-only-auth -->
<!-- planned-change:telec-startup-does-only-auth -->
- The inherited-principal branch returns `HUMAN_ROLE_CUSTOMER` when `human_role` is missing even for `"system:"` inherited principals. Downstream resolution (system-role derivation in caller verification) re-derives the system role from the live session record and the `working_slug` heuristic; the inherited token's role value is not used for clearance on a child session.
<!-- change:telec-startup-does-only-auth -->
- The inherited-principal branch returns `HUMAN_ROLE_CUSTOMER` when `human_role` is missing even for `"system:"` inherited principals. The client-side caller resolution derives the system role from the live session record and the `working_slug` heuristic; the returned role value is not used for clearance on a child session.
<!-- /planned-change:telec-startup-does-only-auth -->
- The fallback role for `human:` principals without an explicit `human_role` is the lowest band (`customer`). This is intentional fail-closed behavior — a session lacking role metadata cannot escalate.
<!-- planned-change:telec-startup-does-only-auth -->
- The error type is a session-identity error. The identity context's caller-verification surface catches it and emits authentication-required; lower layers may surface it as an uncaught exception if they bypass verification.
<!-- change:telec-startup-does-only-auth -->
- The error type is a session-identity error. The client-side caller resolution catches it and treats the caller as holding no identity; lower layers may surface it as an uncaught exception if they call the capability directly.
<!-- /planned-change:telec-startup-does-only-auth -->
