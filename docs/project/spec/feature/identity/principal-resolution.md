---
id: 'project/spec/feature/identity/principal-resolution'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Derive the canonical `(principal, role)` pair for a v1 session from its inherited principal, human email, or system role.'
---

# Principal Resolution — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 rule for turning a session record into the `(principal, role)` pair that downstream authorization uses. Every authenticated CLI call into the identity context ultimately reaches a path that requires this resolution: tokens carry a `principal` stamped at issuance time, and that stamp is produced by this single capability. The capability answers "who is this session, and what authorization band does it carry?" with three deterministic rules — inherited principal wins, then human identity, then system identity — and raises a typed identity error when none apply.

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
Then principal is "system:<session_id>"
And role is the session's system_role (e.g. "worker", "orchestrator", "integrator", "system")
```

```
Given a session with no principal, no human_email, and no system_role
When principal resolution runs over the session
Then a session-identity error is raised with a diagnostic naming the session_id
And the identity context surfaces this as an authentication-required failure
```

```
Given an inherited principal of "system:<parent-session-id>" on a child session
When principal resolution runs over the session
Then the child returns the parent's "system:<parent-session-id>" principal verbatim
And the agent chain shares one stable identity across orchestrator → worker → integrator
```

### Cross-context references

- Consumer: `agent_runtime` session bootstrap calls this capability to decide whether to issue a session token (system-principal sessions only).
- The returned `principal` value is stamped into the session-token ledger entry at issuance, and read back by caller verification on the token path — see `feature/identity/session-token-issuance` and `feature/identity/caller-verification`.
- No domain events are emitted by this capability directly. In v2 it corresponds to the materialization of a `Principal` aggregate, which DOES emit `identity.principal.created` on first issuance.

## Known caveats

- The capability returns `role`, but the contract notes it is "informational only — system sessions get their authoritative role from session.system_role, not from this capability." In practice the returned role is only used as the token's `role` value at issuance time; the v2 model collapses this ambiguity.
- The inherited-principal branch returns `HUMAN_ROLE_CUSTOMER` when `human_role` is missing even for `"system:"` inherited principals. Downstream resolution (system-role derivation in caller verification) re-derives the system role from the live session record and the `working_slug` heuristic; the inherited token's role value is not used for clearance on a child session.
- The fallback role for `human:` principals without an explicit `human_role` is the lowest band (`customer`). This is intentional fail-closed behavior — a session lacking role metadata cannot escalate.
- The error type is a session-identity error. The identity context's caller-verification surface catches it and emits authentication-required; lower layers may surface it as an uncaught exception if they bypass verification.
