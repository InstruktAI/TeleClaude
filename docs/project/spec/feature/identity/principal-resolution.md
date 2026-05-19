---
id: project/spec/feature/identity/principal-resolution
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Derive the canonical `(principal, role)` pair for a v1 session from its inherited principal, human email, or system role.
---

# Principal Resolution — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 rule for turning a `Session` record into the `(principal, role)` pair that downstream authorization uses. Every authenticated CLI call into the daemon's API ultimately reaches a path that requires this resolution: tokens carry a `principal` stamped at issuance time, and that stamp is produced by this single function. The function answers "who is this session, and what authorization band does it carry?" with three deterministic rules — inherited principal wins, then human identity, then system identity — and raises a typed error when none apply.

## Canonical fields

### Use cases

```
Given a session whose `principal` column is already set (parent-inherited identity)
When resolve_session_principal(session) is called
Then the inherited principal is returned verbatim
And the role is session.human_role when present, else HUMAN_ROLE_CUSTOMER ("customer")
```

```
Given a session with human_email set and no inherited principal
When resolve_session_principal(session) is called
Then principal is "human:<email>" using the session's human_email
And role is session.human_role when present, else HUMAN_ROLE_CUSTOMER
```

```
Given a session with system_role set (no human_email, no inherited principal)
When resolve_session_principal(session) is called
Then principal is "system:<session_id>"
And role is the session's system_role (e.g. "worker", "orchestrator", "integrator", "system")
```

```
Given a session with no principal, no human_email, and no system_role
When resolve_session_principal(session) is called
Then SessionIdentityError is raised with a diagnostic naming the session_id
And the daemon surfaces this as an HTTP 401 ("Authentication required")
```

```
Given an inherited principal of "system:<parent-session-id>" on a child session
When resolve_session_principal(session) is called
Then the child returns the parent's "system:<parent-session-id>" principal verbatim
And the agent chain shares one stable identity across orchestrator → worker → integrator
```

### Implementation pointers (v1)

- Resolution function: `teleclaude/core/db/_sync.py:166-192` (`resolve_session_principal`)
- `SessionIdentityError`: `teleclaude/core/db/_sync.py:162-164`
- Re-export: `teleclaude/core/db/__init__.py:29,89`
- Live caller (token issuance): `teleclaude/core/session_bootstrap.py:41-44`
- Default role fallback constant: `teleclaude/constants.py:55` (`HUMAN_ROLE_CUSTOMER = "customer"`)
- Session columns consulted: `teleclaude/core/db_models.py:29,50,51,52` (`system_role`, `human_email`, `human_role`, `principal`)

### Cross-context references

- Consumer: `agent_runtime` session bootstrap calls this function to decide whether to issue a session token (system-principal sessions only).
- The returned `principal` value is stamped into the `session_tokens.principal` column at issuance, and read back by `verify_caller` token-path resolution — see `feature/identity/session-token-issuance` and `feature/identity/caller-verification`.
- No domain events are emitted by this function directly. In v2 it corresponds to the materialization of a `Principal` aggregate, which DOES emit `identity.principal.created` on first issuance.

## Known caveats

- The function name returns `role` but the docstring marks it "informational only — system sessions get their authoritative role from session.system_role, not from this function." In practice the returned role is only used as the token's `role` column at issuance time; the v2 model collapses this ambiguity.
- The inherited-principal branch returns `HUMAN_ROLE_CUSTOMER` when `human_role` is missing even for `"system:"` inherited principals. Downstream code (e.g. `_derive_session_system_role` in `api/auth.py`) re-derives the system role from `session.system_role` and the `working_slug` heuristic; the inherited token's role column is not used for clearance on a child session.
- The fallback role for `human:` principals without an explicit `human_role` is the lowest band (`customer`). This is intentional fail-closed behavior — a session lacking role metadata cannot escalate.
- The error type is `SessionIdentityError` (a `ValueError` subclass). API layers catch it and emit 401; lower layers may surface it as an uncaught exception if they bypass `verify_caller`.
