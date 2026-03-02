# Implementation Plan: agent-session-auth

## Overview

Add a token-based credential system for agent sessions. The daemon generates a short-lived token at session bootstrap, stores it in a `session_tokens` ledger table, injects it as a tmux env var, and validates it on every CLI request. This builds on the existing dual-factor auth (`X-Caller-Session-Id` + `X-Tmux-Session`) by adding a proper credential that can be issued, validated, and revoked independently of the session ID.

The approach follows existing patterns: token injection mirrors voice env var injection in `_bootstrap_session_resources()`, the ledger table follows the same SQLite + SQLAlchemy ORM pattern as all other tables, and auth validation extends the existing `verify_caller()` dependency.

## Phase 1: Token Ledger

### Task 1.1: Add `session_tokens` table

**File(s):** `teleclaude/core/schema.sql`, `teleclaude/core/migrations/026_add_session_tokens.py`

- [ ] Add `session_tokens` table to `schema.sql`:
  ```sql
  CREATE TABLE IF NOT EXISTS session_tokens (
      token TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      principal TEXT NOT NULL,       -- "human:<email>" or "system:<session_id_prefix>"
      issued_at TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      revoked_at TEXT,
      FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_session_tokens_session ON session_tokens(session_id);
  CREATE INDEX IF NOT EXISTS idx_session_tokens_expires ON session_tokens(expires_at);
  ```
- [ ] Write migration `026_add_session_tokens.py` that creates the table and indexes

### Task 1.2: Add SessionToken ORM model

**File(s):** `teleclaude/core/db_models.py`

- [ ] Add `SessionToken(SQLModel, table=True)` with fields matching the schema: `token`, `session_id`, `principal`, `issued_at`, `expires_at`, `revoked_at`

### Task 1.3: Add token DB operations

**File(s):** `teleclaude/core/db.py`

- [ ] `issue_session_token(session_id, principal) -> str` — generate UUID token, store in `session_tokens` with `issued_at=now`, `expires_at=now+24h`. Return the token string.
- [ ] `validate_session_token(token) -> SessionToken | None` — look up token, verify not expired (`expires_at > now`) and not revoked (`revoked_at IS NULL`). Return the record or None.
- [ ] `revoke_session_tokens(session_id)` — set `revoked_at=now` on all tokens for the session.

---

## Phase 2: Token Issuance at Bootstrap

### Task 2.1: Resolve principal from session state

**File(s):** `teleclaude/core/db.py` (inline helper, or add to existing auth utilities)

- [ ] Add `resolve_session_principal(session: Session) -> str`:
  - If `session.human_email` → `"human:{email}"`
  - Else → `"system:{session_id[:8]}"`
- [ ] This follows the two principal types from requirements: human-delegated and system/job

### Task 2.2: Issue token and inject into tmux env

**File(s):** `teleclaude/daemon.py`

- [ ] In `_bootstrap_session_resources()`, after getting the session and before calling `ensure_tmux_session()`:
  1. Call `resolve_session_principal(session)` to get the principal
  2. Call `db.issue_session_token(session_id, principal)` to get the token
  3. Add `env_vars["TELEC_SESSION_TOKEN"] = token` (same pattern as voice env vars at line 1221)
- [ ] The token is injected via `-e TELEC_SESSION_TOKEN=<token>` into the tmux session, making it available to all processes in that session

---

## Phase 3: Token Validation in Auth

### Task 3.1: Accept `X-Session-Token` header in auth middleware

**File(s):** `teleclaude/api/auth.py`

- [ ] Add `x_session_token: Annotated[str | None, Header()] = None` parameter to `verify_caller()`
- [ ] Add token validation path at the top of `verify_caller()`, before the existing `x_caller_session_id` check:
  ```
  if x_session_token:
      token_record = await db.validate_session_token(x_session_token)
      if not token_record: raise 401
      session = get_session(token_record.session_id)  # use session cache
      system_role = _derive_session_system_role(session)
      return CallerIdentity(session_id=token_record.session_id, system_role=..., human_role=..., principal=token_record.principal)
  ```
- [ ] Add `principal: str | None = None` field to `CallerIdentity` dataclass
- [ ] Existing dual-factor auth continues to work as fallback for TUI/terminal callers

### Task 3.2: Send token from CLI client

**File(s):** `teleclaude/cli/api_client.py`

- [ ] In `_build_identity_headers()`, add token reading:
  ```python
  token = os.environ.get("TELEC_SESSION_TOKEN")
  if token:
      headers["x-session-token"] = token
  ```
- [ ] This runs before session_id and email headers — the daemon handles priority

---

## Phase 4: Revocation on Session Close

### Task 4.1: Revoke tokens when session closes

**File(s):** `teleclaude/core/db.py`

- [ ] In `close_session()`, call `self.revoke_session_tokens(session_id)` before emitting `SESSION_CLOSED` event
- [ ] This ensures any subsequent CLI calls with the token are rejected

### Task 4.2: Token cache for validation performance

**File(s):** `teleclaude/api/auth.py`

- [ ] Add a token-to-session cache (same pattern as `_session_cache`): `_token_cache: dict[str, tuple[float, SessionToken]]`
- [ ] TTL: 30 seconds (matching session cache)
- [ ] Invalidate on session close via existing `invalidate_session_cache()` path (or add `invalidate_token_cache()`)

---

## Phase 5: `telec auth whoami` Update

### Task 5.1: Return principal in agent sessions

**File(s):** `teleclaude/cli/session_auth.py` or the whoami API route

- [ ] When `TELEC_SESSION_TOKEN` is set, whoami should call the daemon to resolve the principal
- [ ] Return format: `"Principal: human:maurice@instrukt.ai"` or `"Principal: system:a1b2c3d4"`
- [ ] Falls back to existing terminal email display when no token is present

---

## Phase 6: Validation

### Task 6.1: Unit tests for token DB operations

**File(s):** `tests/unit/test_session_tokens.py`

- [ ] Test `issue_session_token()` creates a valid record
- [ ] Test `validate_session_token()` succeeds for valid token
- [ ] Test `validate_session_token()` returns None for expired token
- [ ] Test `validate_session_token()` returns None for revoked token
- [ ] Test `revoke_session_tokens()` marks all session tokens as revoked
- [ ] Test principal resolution: human email → `human:<email>`, no email → `system:<prefix>`

### Task 6.2: Auth middleware tests for token path

**File(s):** `tests/unit/test_api_auth.py`

- [ ] Test `verify_caller()` accepts valid `X-Session-Token` header
- [ ] Test `verify_caller()` rejects invalid/expired/revoked token with 401
- [ ] Test token path takes priority over session_id path when both present
- [ ] Test `CallerIdentity.principal` is populated from token record

### Task 6.3: Integration test for bootstrap flow

**File(s):** `tests/unit/test_api_server.py` or `tests/integration/`

- [ ] Test session bootstrap issues token and stores in DB
- [ ] Test token is present in tmux env vars
- [ ] Test session close revokes the token
- [ ] Test post-close CLI calls with the token are rejected

### Task 6.4: Quality checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 7: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
