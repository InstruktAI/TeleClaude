---
description: 'Derive the canonical `(principal, role)` pair for a v1 session from its inherited principal, human email, or system role.'
visibility: 'public'
---

# Principal Resolution — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

The v1 rule for turning a session record into the `(principal, role)` pair that downstream authorization uses. Every caller the client resolves from a session reaches this resolution: the principal the client carries on its requests is produced by this single capability. The capability answers "who is this session, and what authorization band does it carry?" with three deterministic rules — inherited principal wins, then human identity, then system identity — and raises a typed identity error when none apply. System-origin sessions resolve to the shared principal `system:daemon`, with their own session records remaining distinct. A principal-less help-desk session carrying `customer` may still be treated as a customer for role-only decisions; that fallback creates no principal and does not satisfy principal resolution.

## Canonical fields

### Use cases

#### UC-PR-CUSTOMER-ROLE: A principal-less customer session still reads as a customer

### Cross-context references

- Consumer: the client-side caller resolution (`local/projects/teleclaude/spec/identity-and-auth` §6) resolves a session caller's principal through this capability.
- No domain events are emitted by this capability directly. In v2 it corresponds to the materialization of a `Principal` aggregate, which DOES emit `identity.principal.created` on first issuance.

## Known caveats

- The capability returns `role`, but the contract notes it is "informational only — system sessions get their authoritative role from session.system_role, not from this capability." No consumer reads the returned role for a system principal; the v2 model collapses this ambiguity.
- The inherited-principal branch returns `HUMAN_ROLE_CUSTOMER` when `human_role` is missing even for `"system:"` inherited principals. The client-side caller resolution derives the system role from the live session record and the `working_slug` heuristic; the returned role value is not used for clearance on a child session.
- The fallback role for `human:` principals without an explicit `human_role` is the lowest band (`customer`). This is intentional fail-closed behavior — a session lacking role metadata cannot escalate.
- The error type is a session-identity error. The client-side caller resolution catches it and treats the caller as holding no identity; lower layers may surface it as an uncaught exception if they call the capability directly.
