# Implementation Plan: agent-session-auth

## Overview

Add a token-based credential system for agent sessions. The daemon generates a token at session bootstrap, stores it in a `session_tokens` ledger table, injects it as a tmux env var (`TELEC_SESSION_TOKEN`), and validates it on every CLI request. This builds on the existing dual-factor auth (`X-Caller-Session-Id` + `X-Tmux-Session`) by adding a proper credential that can be issued, validated, and revoked independently of the session ID.

The token carries a principal (identity) and a role (authorization). The principal establishes *who* the session is (`human:<email>` or `system:<id>`). The role establishes *what* the session may do. Together they replace the `human_role` requirement for daemon-spawned sessions that have no human behind them.

The approach follows existing patterns: token injection mirrors voice env var injection in `_bootstrap_session_resources()`, the ledger table follows the same SQLite + SQLAlchemy ORM pattern as all other tables, and auth validation extends the existing `verify_caller()` dependency.

## Phase 1: Token Ledger

### Task 1.1: Add `session_tokens` table

**File(s):** `teleclaude/core/schema.sql`, `teleclaude/core/migrations/031_add_session_tokens.py`
**Why:** Token issuance, expiry, and revocation need a daemon-owned source of truth instead of implicit trust in session IDs.
**Verify:** Migration applies cleanly and the schema exposes the table plus the session/expiry indexes.

- [x] Add `session_tokens` table to `schema.sql`:
  ```sql
  CREATE TABLE IF NOT EXISTS session_tokens (
      token TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      principal TEXT NOT NULL,       -- "human:<email>" or "system:<stable-id>"
      role TEXT NOT NULL,            -- authorization role (e.g. "admin", "worker")
      issued_at TEXT NOT NULL,
      expires_at TEXT NOT NULL,
      revoked_at TEXT,
      FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
  );
  CREATE INDEX IF NOT EXISTS idx_session_tokens_session ON session_tokens(session_id);
  CREATE INDEX IF NOT EXISTS idx_session_tokens_expires ON session_tokens(expires_at);
  ```
- [x] Write migration `031_add_session_tokens.py` that creates the table and indexes

### Task 1.2: Add SessionToken ORM model

**File(s):** `teleclaude/core/db_models.py`
**Why:** The auth flow already uses SQLModel-backed records; the token ledger should use the same ORM boundary as the rest of `teleclaude.db`.
**Verify:** ORM reads and writes preserve the same fields and nullability as the SQL schema.

- [x] Add `SessionToken(SQLModel, table=True)` with fields matching the schema: `token`, `session_id`, `principal`, `role`, `issued_at`, `expires_at`, `revoked_at`

### Task 1.3: Add token DB operations

**File(s):** `teleclaude/core/db.py`
**Why:** Issuance, validation, and revocation belong at the DB boundary so the daemon and auth middleware share one contract.
**Verify:** Targeted DB tests cover valid, expired, revoked, and bulk-revocation paths.

- [x] `issue_session_token(session_id, principal, role) -> str` — generate UUID token, store in `session_tokens` with `issued_at=now`, `expires_at=now+24h`. Return the token string.
- [x] `validate_session_token(token) -> SessionToken | None` — look up token, verify not expired (`expires_at > now`) and not revoked (`revoked_at IS NULL`). Return the record or None.
- [x] `revoke_session_tokens(session_id)` — set `revoked_at=now` on all tokens for the session.

---

## Phase 2: Token Issuance at Bootstrap

### Task 2.1: Resolve principal and role from session state

**File(s):** `teleclaude/core/db.py` (inline helper, or add to existing auth utilities)
**Why:** Bootstrap must mint the same principal shape for every session so downstream auth and child-session inheritance remain deterministic.
**Verify:** Resolution tests cover both principal types and confirm system principals use a stable, traceable, non-truncated identifier.

- [x] Add `resolve_session_principal(session: Session) -> tuple[str, str]` returning `(principal, role)`:
  - If `session.human_email` → `("human:{email}", session.human_role or "admin")`
  - Else → `("system:<stable-id>", "admin")`, where the identifier comes from existing job/session lineage without truncating IDs
- [x] This follows the two principal types from requirements: human-delegated and system/job
- [x] The role is carried with the principal so authorization checks never encounter a role-less credential

### Task 2.2: Issue token and inject into tmux env

**File(s):** `teleclaude/daemon.py`
**Why:** The daemon is the only safe issuer for agent credentials, and tmux env injection is the existing pattern for session-scoped runtime state.
**Verify:** Bootstrap tests show the token is issued before tmux creation completes and is available to the first process in the session.

- [x] In `_bootstrap_session_resources()`, after getting the session and before calling `ensure_tmux_session()`:
  1. Call `resolve_session_principal(session)` to get `(principal, role)`
  2. Call `db.issue_session_token(session_id, principal, role)` to get the token
  3. Add `env_vars["TELEC_SESSION_TOKEN"] = token` (same pattern as voice env vars)
- [x] The token is injected via `-e TELEC_SESSION_TOKEN=<token>` into the tmux session, making it available to all processes in that session

---

## Phase 3: Token Validation in Auth

### Task 3.1: Extend `CallerIdentity` with principal

**File(s):** `teleclaude/api/auth.py`
**Why:** Clearance checks need both the caller identity and the token-carried authorization role without re-querying the ledger after auth.
**Verify:** Token-authenticated requests can propagate principal identity and principal-scoped role through `CallerIdentity`.

- [x] Add `principal: str | None = None` field to `CallerIdentity` dataclass
- [x] Add `principal_role: str | None = None` field to `CallerIdentity` dataclass

### Task 3.2: Accept `X-Session-Token` header in auth middleware

**File(s):** `teleclaude/api/auth.py`
**Why:** The daemon must validate the token before trusting an agent session; the existing dual-factor path remains for human TUI/terminal callers.
**Verify:** Auth tests cover valid, invalid, expired, and revoked tokens plus precedence over the legacy session-id path.

- [x] Add `x_session_token: Annotated[str | None, Header()] = None` parameter to `verify_caller()`
- [x] Add token validation path at the top of `verify_caller()`, before the existing `x_caller_session_id` check:
  ```python
  if x_session_token:
      token_record = await db.validate_session_token(x_session_token)
      if not token_record: raise 401
      session = _get_cached_session(token_record.session_id) or await db.get_session(token_record.session_id)
      if not session: raise 401
      system_role = _derive_session_system_role(session)
      return CallerIdentity(
          session_id=token_record.session_id,
          system_role=system_role,
          human_role=session.human_role,  # may be None for daemon-spawned
          tmux_session_name=session.tmux_session_name,
          principal=token_record.principal,
          principal_role=token_record.role,
      )
  ```
- [x] Existing dual-factor auth continues to work as fallback for TUI/terminal callers

### Task 3.3: Send token from CLI client

**File(s):** `teleclaude/cli/api_client.py`
**Why:** Agent-initiated CLI calls should present their daemon-issued credential automatically instead of requiring each command path to special-case auth.
**Verify:** Client tests cover header emission when `TELEC_SESSION_TOKEN` is present and absence when it is not.

- [x] In `_build_identity_headers()`, add token reading:
  ```python
  token = os.environ.get("TELEC_SESSION_TOKEN")
  if token:
      headers["x-session-token"] = token
  ```
- [x] This runs before session_id and email headers — the daemon handles priority

### Task 3.4: Update clearance check to accept principals

**File(s):** `teleclaude/cli/telec.py`
**Why:** Clearance must still fail closed for anonymous callers while allowing token-backed agent principals whose authorization role is not represented by `human_role`.
**Verify:** Principal-only sessions are permitted when their token role allows the command, and anonymous callers remain denied.

- [x] Update `is_command_allowed()` signature to accept `principal: str | None = None` and `principal_role: str | None = None`
- [x] Change the `human_role is None` denial (line ~1019) to:
  ```python
  if human_role is None and principal is None:
      return False
  ```
- [x] When `principal` is present and `human_role` is None, use `principal_role` for the human-role allowlist check instead of re-reading the ledger downstream.
- [x] Update `_is_tool_denied()` in `auth.py` to pass `identity.principal` and `identity.principal_role` to `is_command_allowed()`

---

## Phase 4: Principal Inheritance for Child Sessions

### Task 4.1: Thread principal through session spawning

**File(s):** `teleclaude/api_server.py`, `teleclaude/core/command_handlers.py`
**Why:** Child sessions must inherit the parent principal or the auth chain breaks as soon as an agent dispatches another agent.
**Verify:** Session-creation tests show the principal is preserved from API request through `channel_metadata` into the created child session.

- [x] In `POST /sessions/run` handler (~line 1416): when `identity.principal` is present, add it to `channel_metadata`:
  ```python
  if identity.principal:
      channel_metadata = channel_metadata or {}
      channel_metadata["principal"] = identity.principal
  ```
- [x] In `command_handlers.py` `create_session()` (~line 328): inherit principal from parent session when resolving identity, same pattern as human_email/human_role inheritance
- [x] Store principal on the session record (add `principal` column to sessions table, migration 032) so child sessions can inherit it

### Task 4.2: Issue child token with inherited principal

**File(s):** `teleclaude/daemon.py`
**Why:** Every child session needs its own revocable token, but the principal identity must remain continuous across the agent chain.
**Verify:** Bootstrap tests confirm child tokens reuse the inherited principal rather than deriving a new system identity.

- [x] In `_bootstrap_session_resources()`, when resolving the principal: if the session has an inherited principal (from parent), use that instead of deriving a new one
- [x] This ensures the full chain daemon → agent → child agent shares the same principal identity

---

## Phase 5: Revocation on Session Close

### Task 5.1: Revoke tokens when session closes

**File(s):** `teleclaude/core/session_cleanup.py`
**Why:** Token validity must end with session lifetime even if the agent process lingers or cached headers are replayed.
**Verify:** Lifecycle tests prove a closed session token is rejected immediately on the next CLI/API call.

- [x] In `terminate_session()`, call `db.revoke_session_tokens(session_id)` early in the cleanup sequence
- [x] This ensures any subsequent CLI calls with the token are rejected, regardless of how the session ended (API, UI adapter, inactivity, stale detection)

### Task 5.2: Token cache for validation performance

**File(s):** `teleclaude/api/auth.py`
**Why:** Token validation will sit on every protected CLI call, so it should mirror the existing session cache without weakening revocation semantics.
**Verify:** Cache tests cover hit/miss behavior and invalidation on session close.

- [x] Add a token-to-session cache (same pattern as `_session_cache`): `_token_cache: dict[str, tuple[float, SessionToken]]`
- [x] TTL: 30 seconds (matching session cache)
- [x] Invalidate on session close via existing `invalidate_session_cache()` path (or add `invalidate_token_cache()`)

---

## Phase 6: `telec auth whoami` Update

### Task 6.1: Return principal in agent sessions

**File(s):** `teleclaude/cli/telec.py` (`_handle_whoami()`)
**Why:** `telec auth whoami` must give operators and builders an observable way to confirm which principal an agent session is running under.
**Verify:** Handler tests confirm agent sessions surface the resolved principal path and non-agent sessions still use the terminal-email path without prose-locking the full message.

- [x] When `TELEC_SESSION_TOKEN` is set, whoami should call the daemon to resolve the principal
- [x] Return format conveys the resolved principal, for example `"Principal: human:<email>"` or `"Principal: system:<stable-id>"`
- [x] Falls back to existing terminal email display when no token is present

---

## Phase 7: Validation

### Task 7.1: Unit tests for token DB operations

**File(s):** `tests/unit/test_session_tokens.py`
**Why:** The ledger is the root contract for token auth, so expiry, revocation, and principal resolution need isolated tests before the higher-level flows build on them.
**Verify:** Run the targeted token test file through RED/GREEN until all ledger edge cases pass.

- [x] Test `issue_session_token()` creates a valid record with role
- [x] Test `validate_session_token()` succeeds for valid token
- [x] Test `validate_session_token()` returns None for expired token
- [x] Test `validate_session_token()` returns None for revoked token
- [x] Test `revoke_session_tokens()` marks all session tokens as revoked
- [x] Test principal resolution: human email → `human:<email>` with role, no email → `system:<stable-id>` with admin role and no truncated identifier leakage

### Task 7.2: Auth middleware tests for token path

**File(s):** `tests/unit/test_api_auth.py`
**Why:** `verify_caller()` is the authorization boundary; token precedence and rejection behavior must be proven directly at that boundary.
**Verify:** Run the targeted auth test file and confirm token failures fail for the expected auth reason, not for setup errors.

- [x] Test `verify_caller()` accepts valid `X-Session-Token` header
- [x] Test `verify_caller()` rejects invalid/expired/revoked token with 401
- [x] Test token path takes priority over session_id path when both present
- [x] Test `CallerIdentity.principal` is populated from token record
- [x] Test `CallerIdentity.principal_role` is populated from token record

### Task 7.3: Clearance tests for principal-based authorization

**File(s):** `tests/unit/test_api_auth.py` or `tests/unit/test_telec_auth.py`
**Why:** Command gating is the user-visible enforcement point; it must allow properly credentialed agents without reopening anonymous access.
**Verify:** Clearance tests prove both the positive path (principal-backed) and negative path (no principal, no role).

- [x] Test `is_command_allowed()` permits calls when principal is present and human_role is None
- [x] Test `is_command_allowed()` uses `principal_role` for the human-role allowlist check when `human_role` is absent
- [x] Test `is_command_allowed()` still denies when both principal and human_role are None

### Task 7.4: Inheritance tests

**File(s):** `tests/unit/test_api_server.py` or `tests/integration/`
**Why:** Parent-to-child principal inheritance is the easiest place for session auth to silently regress once multi-session dispatch starts chaining.
**Verify:** Session-spawn tests cover metadata threading, persisted principal inheritance, and child-token issuance.

- [x] Test child session inherits parent's principal via channel_metadata
- [x] Test child session receives its own token with the inherited principal
- [x] Test principal chain: daemon → agent → child agent all share the same principal

### Task 7.5: Integration test for full lifecycle

**File(s):** `tests/unit/test_api_server.py` or `tests/integration/`
**Why:** The core promise is end-to-end: bootstrap issues a credential, agent commands succeed while the session lives, and revocation shuts them back down.
**Verify:** Run the narrowest integration chain that exercises bootstrap, an agent-initiated CLI call, and post-close rejection before broadening further.

- [x] Test session bootstrap issues token and stores in DB
- [x] Test token is present in tmux env vars
- [x] Test a token-authenticated agent session can complete `telec sessions send` with the expected role
- [x] Test `telec auth whoami` resolves the principal inside an agent session without asserting on full human-facing prose
- [x] Test session close revokes the token
- [x] Test post-close CLI calls with the token are rejected

### Task 7.6: Quality checks

**Why:** Verification should follow repository policy: hooks first, targeted runs during development, broader suites only when evidence says they are needed.
**Verify:** Pre-commit hooks pass, targeted auth/session tests are green, and any broader reruns are justified by a failing hook or inconclusive targeted result.

- [x] Run the repository's pre-commit hooks as the primary verification path
- [x] Run targeted unit/integration tests for the touched auth/session files during RED/GREEN; broaden only if hooks fail or targeted runs are inconclusive
- [x] Run lint/type-check commands directly only when isolating a hook failure or when a required check is not covered by hooks
- [x] Verify no unchecked implementation tasks remain

---

## Phase 8: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Update `docs/project/spec/identity-and-auth.md` (and any touched CLI/README surface) so the token-auth path and `whoami` behavior match the delivered code
- [x] Update `todos/agent-session-auth/demo.md` with an executable flow that shows principal resolution and an agent-initiated command succeeding before revocation
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)
