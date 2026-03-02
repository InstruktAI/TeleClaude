# DOR Report: agent-session-auth

## Gate Verdict: PASS (score 9/10)

All eight DOR gates satisfied. Artifacts are well-grounded in codebase evidence.
One minor tightening applied (whoami file path corrected). Assumptions are reasonable
defaults, explicitly documented, and non-blocking.

---

### 1. Intent & Success — PASS

The problem and outcome are explicit in `requirements.md`:
- Every agent session gets a verifiable identity token
- Two principal types: `human:<email>` and `system:<session_id_prefix>`
- Token stored in a ledger, validated on every CLI call, revoked on session close

Six concrete success criteria are testable and specific. Each maps directly to an
implementation plan task.

### 2. Scope & Size — PASS

The work is atomic: one new table, one token lifecycle (issue -> validate -> revoke),
integration into three existing flows (bootstrap, auth middleware, session close).

Touch points verified against codebase:
- `schema.sql` + migration 026 (next after existing 025)
- `db_models.py` (new SessionToken model, follows SQLModel pattern at line 57)
- `db.py` (3 new methods + 1 helper + hook in `close_session()` at line 700)
- `daemon.py` (env var injection in `_bootstrap_session_resources()` at line 1212, same pattern as voice env vars at lines 1219-1221)
- `api/auth.py` (token path in `verify_caller()` at line 162, CallerIdentity extension at line 153)
- `cli/api_client.py` (token header in `_build_identity_headers()` at line 364)
- `cli/telec.py` (whoami update in `_handle_whoami()` at ~line 3145)
- Tests (3 test files)

Fits a single AI session without context exhaustion.

### 3. Verification — PASS

Clear verification path:
- Unit tests for token DB operations (issue, validate, revoke, expire)
- Auth middleware tests for token header path
- Integration test for bootstrap -> env injection -> auth -> revocation
- Demo plan with concrete manual validation steps and guided presentation

### 4. Approach Known — PASS

Every component follows established codebase patterns. Verified against actual code:

| Component | Existing Pattern | Location |
|-----------|-----------------|----------|
| Table + migration | 25 existing migrations | `teleclaude/core/migrations/` |
| ORM model | SQLModel pattern (Session, etc.) | `db_models.py:57` |
| Env var injection | Voice env vars | `daemon.py:1219-1221` |
| Auth header | `X-Caller-Session-Id` dual-factor | `auth.py:162-237` |
| Cache | `_session_cache` TTL cache | `auth.py:46-70` |
| Revocation in close | Event-driven `close_session()` | `db.py:700-716` |
| Identity headers | `_build_identity_headers()` | `api_client.py:364-379` |

No novel patterns required.

### 5. Research Complete — PASS

No third-party dependencies. All components are internal: SQLite, SQLAlchemy/SQLModel,
FastAPI dependencies, tmux env vars, `uuid` stdlib. No research gate triggered.

### 6. Dependencies & Preconditions — PASS

No prerequisite tasks in the roadmap. No external system dependencies. The
`TELEC_SESSION_TOKEN` env var is new but follows the `TELEC_*` naming convention
(`TELEC_TUI_SESSION`, `TELEC_AUTH_EMAIL`). No config wizard exposure needed — the
token is daemon-internal, never user-facing.

### 7. Integration Safety — PASS

The change is additive:
- New table (no existing table modifications)
- New auth path in `verify_caller()` — existing dual-factor path untouched as fallback
- TUI/terminal auth completely unaffected (`tc_tui` bridge explicitly out of scope)
- Token is optional: if `TELEC_SESSION_TOKEN` is not set, auth falls through to existing paths
- Aligns with the identity-and-auth spec (`docs/project/spec/identity-and-auth.md`) — adds a third auth factor without modifying the existing two

Rollback: remove migration, revert code. No data dependency on the new table for existing functionality.

### 8. Tooling Impact — N/A

No scaffolding or tooling changes. Automatically satisfied.

---

## Assumptions (inferred, non-blocking)

1. **Token TTL = 24 hours**: Requirements say "TTL = session lifetime" but sessions can
   run for hours. Using 24h as maximum TTL with revocation on close handles the normal
   case. If a session outlives the TTL, the agent falls back to dual-factor auth.

2. **Principal naming**: `human:<email>` and `system:<session_id[:8]>`. Requirements
   mention `system:<job-id>` without defining job-id. Using session_id prefix is
   unambiguous and traceable. The requirements themselves note: "System principal
   identity needs a stable naming scheme before implementation."

3. **Token priority**: When both `X-Session-Token` and `X-Caller-Session-Id` are present,
   the token takes priority. Natural order since token auth is stricter (daemon-issued,
   ledger-backed) than session ID auth.

## Actions Taken

- Corrected whoami file path: `teleclaude/cli/session_auth.py` -> `teleclaude/cli/telec.py:_handle_whoami()` (~line 3145)
- Verified all codebase references in implementation plan against actual source locations
- Confirmed migration numbering (026 follows existing 025)
- Confirmed `CallerIdentity` is a frozen dataclass — `principal` field addition is compatible
- Confirmed no existing `session_tokens` table or similar in the codebase

## Open Questions

None blocking.
