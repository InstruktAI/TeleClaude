# Requirements: Person Identity & Authentication

## Goal

Implement daemon-side identity resolution, session-to-person binding, and role-based
authorization for multi-person TeleClaude deployments. The daemon validates and
propagates identity claims from adapters — it does not implement login flows.

## Problem Statement

TeleClaude currently has zero human identity awareness:

- Sessions have no person binding (no `human_email` or `human_role` fields).
- API server has no auth middleware — any local process can call any endpoint.
- MCP wrapper has AI role filtering but no human role concept.
- Tool gating is AI-role-only (`role_tools.py` checks `ROLE_WORKER`); human roles don't exist.

## Scope

### In scope

1. **PersonEntry config model** — use global config with `email` and `role` fields (`username` optional alias).
2. **Identity resolver service** — lookup by email (primary) and username (secondary).
3. **Session-to-person binding** — DB migration adding `human_email`, `human_role`, and optional `human_username` to sessions table; stamp during creation; propagate to child sessions.
4. **Auth middleware on daemon API** — validate identity from request headers (trusted adapter headers) or signed tokens (TUI auth); attach identity context to request.
5. **Token signing utility** — daemon-issued signed tokens for bearer auth. Symmetric-key HMAC (HS256).
6. **Human role-based tool gating** — extend `role_tools.py` with human role filtering parallel to existing AI role filtering.
7. **Adapter identity integration** — web boundary trusted headers, MCP human identity marker, and bearer-token auth flow.

### Out of scope

- Login UI, email OTP/magic-link flow, email sending (web-interface todo).
- NextAuth integration (web-interface todo).
- Newcomer onboarding wizard UI (web-interface todo).
- OAuth/SSO providers, password auth.
- Full enterprise revocation infrastructure.
- Telegram platform identity capture and person mapping are in scope.

### Relationship to downstream consumers

- **web-interface** — consumes this todo's auth middleware, session binding, and role gating. NextAuth in Next.js resolves login -> proxies to daemon with `X-TeleClaude-Person-Email` / `X-TeleClaude-Person-Role` / optional `X-TeleClaude-Person-Username` headers -> daemon middleware validates and attaches identity.
- **role-based-notifications** — uses person + role metadata from session binding for routing.
- **config-schema-validation** — provides Pydantic models and canonical typed loaders (`load_global_config`, `load_person_config`). This todo must consume them and must not add ad-hoc YAML parsing.

## Research Input (Required)

- `docs/third-party/assistant-ui/index.md` is a required input artifact for
  token design, replay constraints, and key rotation behavior.

## Functional Requirements

### FR1: PersonEntry config model

- PersonEntry includes: `name`, `username`, `email`, `role`.
- Role validates against allowed values: `admin`, `member`, `contributor`, `newcomer`.
- People section lives in global config (`~/.teleclaude/teleclaude.yml`).
- Email is required and is the stable identity key used across the system.
- Username is optional and used as internal alias only.

### FR2: Identity resolver

- Resolve person from: email (exact, primary), username (exact, secondary).
- Resolve trusted people from platform identifiers (telegram user_id now; extensible to future platforms).
- Return normalized identity context with person + platform fields and trust metadata.
- Unknown signals return None (deny at middleware level).
- Resolver reads from config at startup; no runtime config reload required.
- Resolver consumes validated `GlobalConfig.people` from config-schema-validation loaders.
- Resolver cross-references per-person creds from `~/.teleclaude/people/*/teleclaude.yml`.

### FR3: Session-to-person binding

- New fields on sessions table: `human_email TEXT`, `human_role TEXT`, `human_username TEXT NULL`,
  `human_platform TEXT`, `human_platform_user_id TEXT`.
- Set during session creation when identity is available.
- Child sessions (via `initiator_session_id`) inherit parent's human identity.
- Headless sessions (hook-originated) may have null human identity.
- `SessionSummary` and `SessionSummaryDTO` gain `human_email`, `human_role`, optional `human_username`,
  and platform identity fields.

### FR4: Auth middleware

- Pure ASGI middleware on daemon API validates identity on every request (no `BaseHTTPMiddleware`).
- Identity sources (checked in order):
  1. `X-TeleClaude-Person-Email` + `X-TeleClaude-Person-Role` (+ optional `X-TeleClaude-Person-Username`) from trusted web boundary.
  2. `Authorization: Bearer <token>` header with daemon-signed JWT (from TUI).
- Middleware attaches `IdentityContext` to request state.
- Non-public routes return 401 if no identity resolved, 403 if role insufficient.
- Health check and public endpoints exempt from auth.

### FR5: Token signing utility

- `create_auth_token(email, role, ttl, username=None) -> str` — sign JWT with daemon secret.
- `verify_auth_token(token) -> IdentityContext | None` — verify signature, expiry, claims.
- Claims: `sub` (email), `role`, optional `username`, `iat`, `exp`, `iss` ("teleclaude-daemon").
- Secret from config or env var (`TELECLAUDE_AUTH_SECRET`).
- Default TTL: 30 days for TUI tokens.

### FR6: Human role-based tool gating

- New `HUMAN_ROLE_TOOL_POLICY` in `role_tools.py`:
  - `admin`: no restrictions.
  - `member`: exclude deploy, remote session termination, and agent availability mutation.
  - `contributor`: member limits plus no agent spawning or dependency/phase mutation.
  - `newcomer`: read-only tools only.
- New functions: `get_human_role_excluded_tools(role)`, `filter_tools_by_human_role(role, tools)`.
- MCP wrapper reads human identity marker from session TMPDIR and applies human role filter IN ADDITION TO AI role filter.

### FR7: Adapter identity integration

- **MCP wrapper**: Write `teleclaude_human_identity` marker file to session TMPDIR with email, role, optional username, platform, and platform_user_id. Read during tool filtering.
- **Client auth**: a client command can validate identity input, obtain a signed bearer token, and use it for API calls. Token persistence is client-managed and never daemon-host coupled.
- **API (direct)**: Middleware handles auth as described in FR4.
- **Telegram adapter**: capture `effective_user.id` and username at boundary, resolve against person creds mapping, and pass normalized identity context into session creation metadata.

## Non-functional Requirements

1. Auth secret must not be committed to git. Use env var or `.env` file.
2. Token signing uses PyJWT with HS256 (symmetric, daemon signs and verifies its own tokens). Daemon must never persist per-user auth tokens on host filesystem.
3. Audit logging for auth failures and role-gate denials (daemon logger, not a new table).
4. Identity resolver must be fast (config lookup, no DB queries).
5. Greenfield stance: no legacy fallback path is implemented in this todo.

## Security Constraints

1. Daemon-signed tokens are trusted for localhost/LAN only. Public exposure requires TLS + web boundary auth. Tokens are bearer credentials and remain client-side; daemon host storage is prohibited.
2. Admin role should be required for session management on other people's sessions.
3. Role changes in config take effect on next session creation (existing sessions retain the role at creation time).
4. Auth secret rotation invalidates all outstanding bearer tokens.

## Acceptance Criteria

1. PersonEntry with email + role is parseable from global config.
2. Identity resolver correctly maps email and username to person.
3. Sessions table has `human_email`, `human_role`, and nullable `human_username` columns.
4. New sessions created with identity context have person bound.
5. Child sessions inherit parent's human identity.
6. Daemon API middleware validates identity on protected routes.
7. Bearer token issuance works; subsequent API calls are authenticated without daemon-host token files.
8. JWT claims map to internal metadata (`human_email`, `human_role`, optional `human_username`) consistently.
9. Telegram user_id-based lookup maps known users to trusted people; unknown users are explicitly classified (`external`/`unknown`) and handled per policy.
10. Human role filtering blocks restricted tools for non-admin roles.
11. Auth failures are logged with context.
