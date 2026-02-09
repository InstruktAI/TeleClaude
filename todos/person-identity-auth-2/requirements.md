# Requirements: Person Identity Auth — Phase 2: Session Binding & Auth Middleware

## Goal

Add human identity columns to sessions DB, bind identity during session creation, build token signing utility, and add auth middleware to the daemon API.

## Scope

### In scope

1. **DB migration** adding `human_email`, `human_role`, `human_username` to sessions table.
2. **Session model updates** across db_models, models, and api_models.
3. **Session creation binding** — stamp identity during creation; child sessions inherit.
4. **Token signing utility** with PyJWT HS256.
5. **Auth middleware** on daemon API — validate identity from headers or Bearer token.
6. **Unit tests** for tokens and session binding.

### Out of scope

- Identity model and resolver (phase 1).
- Role-based tool gating (phase 3).
- Adapter integration and TUI login (phase 3).

## Functional Requirements

### FR1: DB migration

- Add nullable columns: `human_email TEXT`, `human_role TEXT`, `human_username TEXT`.
- Migration follows existing pattern in `teleclaude/core/migrations/`.
- Safe for SQLite (ALTER TABLE ADD COLUMN, no downtime).

### FR2: Session model updates

- `Session` (db_models.py): add `human_email`, `human_role`, `human_username` optional fields.
- `SessionSummary` (models.py): add same fields.
- `SessionSummaryDTO` (api_models.py): add same fields with `from_core()` mapper update.

### FR3: Session creation binding

- During session creation, if identity context available, set human_email/human_role/human_username.
- Child sessions (via `initiator_session_id`) inherit parent's human identity.
- Headless sessions may have null human identity.

### FR4: Token signing utility

- `create_auth_token(email, role, ttl_days=30, username=None) -> str`.
- `verify_auth_token(token) -> IdentityContext | None`.
- Claims: `sub` (email), `role`, optional `username`, `iat`, `exp`, `iss` ("teleclaude-daemon").
- Secret from `TELECLAUDE_AUTH_SECRET` env var.
- PyJWT with HS256.

### FR5: Auth middleware

- FastAPI middleware validates identity on every request.
- Identity sources (checked in order):
  1. `X-TeleClaude-Person-Email` + `X-TeleClaude-Person-Role` (+ optional username header).
  2. `Authorization: Bearer <token>` with daemon-signed JWT.
- Attaches `IdentityContext` to `request.state.identity`.
- Non-public routes: 401 if no identity, 403 if role insufficient.
- Exempt paths: `/health`, `/ws`.

## Acceptance Criteria

1. Migration runs without error on existing DB.
2. Sessions created with identity have human_email/human_role populated.
3. Child sessions inherit parent's human identity.
4. Token sign → verify round-trip works.
5. Expired/tampered tokens rejected.
6. API middleware rejects unauthenticated non-public requests.
7. Auth failures logged with context.

## Dependencies

- **person-identity-auth-1** must be complete (provides IdentityContext, IdentityResolver).
- **PyJWT** dependency added to pyproject.toml.
