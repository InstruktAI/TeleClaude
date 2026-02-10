# Person Identity & Authentication — Input

## Context

TeleClaude is moving from single-user to multi-person operation on a shared machine.
We need identity resolution and role-aware authorization on the daemon side.

## Architectural Clarification

The daemon does NOT implement login flows. Login is the responsibility of each
adapter's boundary:

- **Web**: NextAuth v5 with email OTP in the Next.js app (web-interface todo).
- **Client auth**: obtains daemon-signed bearer token; persistence is client-managed and never daemon-host coupled.
- **MCP**: child sessions inherit parent's human identity.

The daemon's job is to: resolve identity from adapter signals, bind it to sessions,
validate it on API requests, and enforce role-based access.

## What we need

1. PersonEntry config model with email + role fields (username optional).
2. Identity resolver: email (primary) / username (secondary) → person.
3. Session-to-person binding (DB columns, creation flow, child inheritance).
4. Strict auth middleware on daemon API (validate headers and tokens).
5. Token signing utility for daemon-issued auth (TUI, inter-process).
6. Human role-based tool gating (parallel to existing AI role filtering).
7. Adapter integration (web boundary headers, TUI token flow, MCP human identity marker).

## Identity resolution by entry point

| Entry point        | Identity signal                    | Resolution                                                     |
| ------------------ | ---------------------------------- | -------------------------------------------------------------- |
| Web                | `X-TeleClaude-Person-Email` header | Middleware validates trusted header from Next.js proxy         |
| Client boundary    | `Authorization: Bearer <token>`    | Middleware verifies daemon-signed JWT                          |
| MCP child sessions | Parent session inheritance         | Lookup parent's human_email/human_role (and optional username) |

## Config extension (source of truth)

`PersonEntry` includes:

- `name`
- `email` (primary identity key)
- `username` (optional internal alias)
- `role` (`admin`, `member`, `contributor`, `newcomer`)

People config lives in `~/.teleclaude/teleclaude.yml` (global level).

## Role gating

Human role gating extends tool filtering (parallel to existing AI role system):

- `admin`: full access
- `member`: broad operational access, no destructive/system admin ops
- `contributor`: scoped operational access
- `newcomer`: minimal guided access

The resolved human role is attached to session metadata so wrappers/adapters can
enforce it consistently.

## Identity and token mapping

The daemon maps JWT claims to internal identity metadata as follows:

- `sub` -> `human_email` (required)
- `role` -> `human_role` (required)
- `username` -> `human_username` (optional)

Internal session metadata stores all three fields so authorization and audit
logic can operate without re-parsing transport-specific payloads.

## Breakdown

This todo is split into 3 sequential phases:

1. `person-identity-auth-1` — Identity Model & Config (PersonEntry, resolver, constants)
2. `person-identity-auth-2` — Session Binding & Auth Middleware (DB migration, tokens, middleware)
3. `person-identity-auth-3` — Role Gating & Adapter Integration (tool filtering, web/TUI/MCP boundaries)

## Relationship to other work

- `config-schema-validation`: prerequisite for typed `email` + `role` fields.
- `web-interface`: consumes daemon auth middleware, session binding, and role gating. Handles login flow via NextAuth.
- `role-based-notifications`: uses role/person identity for routing decisions.
