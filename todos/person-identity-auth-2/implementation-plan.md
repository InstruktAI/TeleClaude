# Implementation Plan: Person Identity Auth — Phase 2

## Objective

Add session-to-person binding and auth infrastructure to the daemon.

## Task 1: DB migration

**File:** New migration in `teleclaude/core/migrations/`

```sql
ALTER TABLE sessions ADD COLUMN human_email TEXT;
ALTER TABLE sessions ADD COLUMN human_role TEXT;
ALTER TABLE sessions ADD COLUMN human_username TEXT;
```

**Verification:** Migration runs on existing DB, columns exist.

## Task 2: Session model updates

**Files:**

- `teleclaude/core/db_models.py` — add `human_email`, `human_role`, `human_username` (all `Optional[str] = None`).
- `teleclaude/core/models.py` — add same fields to `SessionSummary`.
- `teleclaude/api_models.py` — add same fields to `SessionSummaryDTO`, update `from_core()`.

**Verification:** Model instantiation with and without identity fields.

## Task 3: Session creation binding

**Files:**

- `teleclaude/core/command_handlers.py` — set identity fields from command metadata during creation.
- `teleclaude/core/db.py` — ensure `create_session()` persists new fields.

Child session inheritance: look up parent's identity via `initiator_session_id`.

**Verification:** Unit test for creation with identity and child inheritance.

## Task 4: Token signing utility

**Files:** New `teleclaude/auth/__init__.py` + `teleclaude/auth/tokens.py`

- `create_auth_token()` and `verify_auth_token()` functions.
- PyJWT with HS256, secret from `TELECLAUDE_AUTH_SECRET`.

**Dependency:** Add `PyJWT>=2.8.0` to `pyproject.toml`.

**Verification:** Token round-trip, expiry rejection, bad secret rejection.

## Task 5: Auth middleware

**File:** `teleclaude/api_server.py`

Add middleware after `_track_requests`:

1. Check identity headers (`X-TeleClaude-Person-Email`, `X-TeleClaude-Person-Role`, optional username).
2. Check `Authorization: Bearer <token>`.
3. Attach `IdentityContext` to `request.state.identity`.
4. Enforce 401/403 on non-public routes.
5. Exempt: `/health`, `/ws`.

**Verification:** Unauthenticated requests rejected, authenticated requests pass.

## Task 6: Unit tests

**Files:**

- `tests/unit/test_auth_tokens.py` — token creation, verification, expiry, bad secret.
- `tests/unit/test_session_binding.py` — creation with identity, child inheritance, middleware rejection.

## Files Changed

| File                                  | Change                                |
| ------------------------------------- | ------------------------------------- |
| `teleclaude/core/migrations/`         | New migration                         |
| `teleclaude/core/db_models.py`        | Add identity columns                  |
| `teleclaude/core/models.py`           | Add identity fields to SessionSummary |
| `teleclaude/api_models.py`            | Add identity fields to DTO            |
| `teleclaude/core/command_handlers.py` | Bind identity on creation             |
| `teleclaude/core/db.py`               | Persist identity fields               |
| `teleclaude/auth/__init__.py`         | New package                           |
| `teleclaude/auth/tokens.py`           | New — token utility                   |
| `teleclaude/api_server.py`            | Add auth middleware                   |
| `pyproject.toml`                      | Add PyJWT dependency                  |
| `tests/unit/test_auth_tokens.py`      | New tests                             |
| `tests/unit/test_session_binding.py`  | New tests                             |

## Risks

1. **PyJWT dependency** — mature, low risk.
2. **Strict auth rollout** — unauthenticated calls to non-public routes will fail. Existing MCP/TUI clients need identity propagation from phase 3.

## Verification

- All tests pass.
- Migration applies cleanly.
- Sessions carry identity when available.
- Token round-trip works.
- Middleware enforces auth.
