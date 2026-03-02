# DOR Report: agent-session-auth

## Draft Assessment

### 1. Intent & Success — PASS

The problem and outcome are explicit in `requirements.md`:
- Every agent session gets a verifiable identity token
- Two principal types: `human:<email>` and `system:<session_id_prefix>`
- Token stored in a ledger, validated on every CLI call, revoked on session close

Six concrete success criteria are testable and specific.

### 2. Scope & Size — PASS

The work is atomic: one new table, one token lifecycle (issue → validate → revoke), integration into three existing flows (bootstrap, auth middleware, session close). No cross-cutting changes beyond the auth boundary.

Estimated touch points:
- `schema.sql` + new migration (table creation)
- `db_models.py` (new model)
- `db.py` (3 new methods + 1 helper + close_session hook)
- `daemon.py` (2 lines in `_bootstrap_session_resources`)
- `api/auth.py` (token validation path + CallerIdentity extension)
- `cli/api_client.py` (1 line to read env var)
- `cli/session_auth.py` or auth route (whoami principal display)
- Tests (3 test files)

Fits a single AI session without context exhaustion.

### 3. Verification — PASS

Clear verification path:
- Unit tests for token DB operations (issue, validate, revoke, expire)
- Auth middleware tests for token header path
- Integration test for bootstrap → env injection → auth → revocation
- Demo script with concrete commands

### 4. Approach Known — PASS

Every component follows established codebase patterns:
- **Table + migration**: Same pattern as 25 existing migrations
- **ORM model**: Same SQLModel pattern as `Session`, `VoiceAssignment`, etc.
- **Env var injection**: Same pattern as voice env vars in `_bootstrap_session_resources()` (daemon.py:1219-1221)
- **Auth header**: Same pattern as `X-Caller-Session-Id` in `verify_caller()` (auth.py:162-237)
- **Cache**: Same TTL cache pattern as `_session_cache` (auth.py:46-70)
- **Revocation in close**: Same event-driven pattern as `close_session()` (db.py:700-716)

No novel patterns required.

### 5. Research Complete — PASS

No third-party dependencies. All components are internal: SQLite, SQLAlchemy, FastAPI dependencies, tmux env vars, `uuid` stdlib. Codebase research complete — all integration points are identified with file paths and line numbers.

### 6. Dependencies & Preconditions — PASS

No prerequisite tasks in the roadmap. No external system dependencies. Configuration: the `TELEC_SESSION_TOKEN` env var name is new but follows the `TELEC_*` naming convention used by `TELEC_TUI_SESSION` and `TELEC_AUTH_EMAIL`.

No new config keys need wizard exposure — the token is daemon-internal.

### 7. Integration Safety — PASS

The change is additive:
- New table (no existing table modifications)
- New auth path in `verify_caller()` — existing dual-factor path is untouched as fallback
- TUI/terminal auth is completely unaffected (requirements explicitly exclude `tc_tui` changes)
- Token is optional: if `TELEC_SESSION_TOKEN` is not set, auth falls through to existing paths

Rollback: remove migration, revert code. No data dependency on the new table for existing functionality.

### 8. Tooling Impact — N/A

No scaffolding or tooling changes. Automatically satisfied.

## Assumptions (inferred, verify before build)

1. **Token TTL = 24 hours**: The requirements say "TTL = session lifetime" but sessions can run for hours. Using 24h as the maximum TTL with revocation on close handles the normal case. If a session runs longer than 24h, the token expires and the agent falls back to dual-factor auth. (Alternatively: no fixed TTL, rely purely on revocation.)

2. **Principal naming**: `human:<email>` and `system:<session_id[:8]>`. The requirements mention `system:<job-id>` but don't define what constitutes a job-id. Using session_id prefix is unambiguous and traceable. Can refine later if a job-id concept emerges.

3. **Token priority**: When both `X-Session-Token` and `X-Caller-Session-Id` are present, the token takes priority. This is the natural order since token auth is stricter (issued by daemon, stored in ledger) than session ID auth (readable from a file).

## Open Questions

None blocking. The assumptions above are reasonable defaults that can be adjusted during build.

## Verdict

**Draft assessment: Ready for gate validation.** All eight DOR gates are satisfiable with the current artifacts.
