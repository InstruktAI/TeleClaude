# Person Identity Auth — Phase 2: Session Binding & Auth Middleware

## Context

This is phase 2 of the person-identity-auth breakdown. Depends on phase 1
(identity model and resolver). See the parent todo's `implementation-plan.md`
for full architectural context.

## Intended Outcome

Add human identity columns to the sessions DB, bind identity during session
creation, build the token signing utility for TUI auth, and add strict
auth middleware to the daemon API.

## What to Build

1. **DB migration** — `ALTER TABLE sessions ADD COLUMN human_email TEXT; ALTER TABLE sessions ADD COLUMN human_role TEXT; ALTER TABLE sessions ADD COLUMN human_username TEXT;`
2. **Session model updates** — add fields to `Session` (db_models.py), `SessionSummary` (models.py), `SessionSummaryDTO` (api_models.py).
3. **Session creation binding** — in command_handlers.py, set human_email/human_role and optional human_username from identity context when available. Child sessions inherit from parent via initiator_session_id.
4. **Token signing utility** — new `teleclaude/auth/tokens.py` with PyJWT HS256. Add PyJWT dependency to pyproject.toml.
5. **Auth middleware** — in api_server.py, strict middleware that resolves IdentityContext from trusted headers or Bearer token, then enforces `401/403` on non-public routes.
6. **Unit tests** for token round-trip and session binding.

## Key Architectural Notes

- DB migration follows existing pattern in `teleclaude/core/migrations/`.
- Session model has 30+ existing fields — add three nullable identity columns.
- `SessionSummary` and `SessionSummaryDTO` both need the new fields.
- Auth middleware goes after existing `_track_requests` middleware in api_server.py.
- Token secret from `TELECLAUDE_AUTH_SECRET` env var — document in .env.sample.

## Verification

- Migration runs without error on existing DB.
- Sessions created with identity have human_email/human_role and optional human_username populated.
- Token sign → verify round-trip works.
- Expired/tampered tokens rejected.
- API middleware rejects unauthenticated non-public requests.
