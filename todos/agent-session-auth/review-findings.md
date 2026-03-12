# Review Findings: agent-session-auth

## Verdict: APPROVE

All Critical and Important findings were resolved during review via auto-remediation. 164 unit tests pass.

---

## Resolved During Review

### Critical

1. **Privilege escalation via duplicated principal logic** — `daemon.py:1333-1337`
   - **Was:** Inline branching (`if session.principal: ... else: resolve_session_principal(session)`) duplicated the canonical `resolve_session_principal` logic. A divergence between the two paths could cause child sessions to re-derive a different role than their parent intended.
   - **Fix:** Removed inline branching. `daemon.py` now calls `resolve_session_principal(session)` unconditionally. The canonical function was extended to handle inherited principals as its first check.
   - **Files:** `teleclaude/daemon.py`, `teleclaude/core/db.py`

2. **Tests replicated logic inline instead of testing production code** — `test_principal_inheritance.py`
   - **Was:** `TestCreateSessionPrincipalInheritance` captured kwargs manually instead of calling the real `create_session` from `command_handlers`. Tests proved the test helper worked, not the production code.
   - **Fix:** Rewrote to call real `create_session` with mocked DB, verifying actual kwargs passed to `db.create_session`.
   - **File:** `tests/unit/test_principal_inheritance.py`

3. **Source inspection anti-pattern in lifecycle test** — `test_session_token_lifecycle.py`
   - **Was:** `test_session_close_invokes_revocation` used `inspect.getsource` to assert that `revoke_session_tokens` appeared in the source code of `_terminate_session_inner`. This is not a behavioral test — it would pass even if the call were commented out behind a dead branch.
   - **Fix:** Replaced with a mock-based behavioral test that calls `_terminate_session_inner` and asserts `revoke_session_tokens` and `invalidate_token_cache` were called with the correct session ID.
   - **File:** `tests/unit/test_session_token_lifecycle.py`

### Important

4. **`object` type annotation in token cache** — `auth.py:55`
   - **Was:** `_token_cache: dict[str, tuple[float, object]]` — the second element was typed as `object` instead of `db_models.SessionToken`, requiring a compensating `isinstance` runtime check.
   - **Fix:** Changed to `dict[str, tuple[float, db_models.SessionToken]]`, removed the unnecessary `isinstance` check in `_get_cached_token`.
   - **File:** `teleclaude/api/auth.py`

5. **Deferred import in session_cleanup.py** — `session_cleanup.py`
   - **Was:** `from teleclaude.api.auth import invalidate_token_cache` was inside the function body of `_terminate_session_inner`.
   - **Fix:** Moved to module-level imports.
   - **File:** `teleclaude/core/session_cleanup.py`

6. **Warning-level log for security failure** — `session_cleanup.py`
   - **Was:** Token revocation failure was logged at `logger.warning` — a security-relevant operation failing should be logged at error level.
   - **Fix:** Changed to `logger.error`.
   - **File:** `teleclaude/core/session_cleanup.py`

7. **Missing `_is_tool_denied` wiring test** — `test_api_auth.py`
   - **Was:** No test verified that `_is_tool_denied` correctly passes `CallerIdentity.principal` and `principal_role` through to `is_command_allowed`.
   - **Fix:** Added `TestIsToolDeniedPrincipalWiring` with two tests: one proving principal fields are passed (admin allowed), one proving denial when both are absent.
   - **File:** `tests/unit/test_api_auth.py`

---

## Scope Verification

All 8 success criteria from requirements.md are covered by the implementation:

1. Token in tmux env at spawn — `daemon.py:_bootstrap_session_resources` issues token and sets `TELEC_SESSION_TOKEN`
2. `telec auth whoami` returns principal — `telec.py:_handle_whoami` resolves principal from daemon `/auth/whoami`
3. `telec sessions send` succeeds — `api_client.py` sends `X-Session-Token` header
4. Ledger records tokens with expiry — `db.py:issue_session_token` stores in `session_tokens` table with 24h TTL
5. Session close revokes token — `session_cleanup.py` calls `revoke_session_tokens` + `invalidate_token_cache`
6. System sessions get system principal — `resolve_session_principal` derives `system:<session_id>`
7. `is_command_allowed` permits with principal — accepts `principal`/`principal_role` params, uses `principal_role` as effective human_role
8. Child sessions inherit principal — `command_handlers.py:create_session` extracts from `channel_metadata`, falls back to parent session

No gold-plating detected. Scope matches requirements exactly.

## Paradigm-Fit

- Token validation follows existing session cache pattern (TTL-based dict, same constants).
- Migration follows existing numbered sequence (031, 032).
- `CallerIdentity` extension follows existing dataclass pattern.
- `resolve_session_principal` follows the project's pattern of pure functions for domain logic.
- Auth middleware token path follows existing session-id path structure.

## Security

- No secrets in diff.
- Token is UUID4 (128-bit random), adequate for session-scoped auth.
- Tokens validated against DB ledger, not decoded locally.
- Revocation is daemon-controlled, not agent-dependent.
- Error messages do not leak internal details (generic 401 responses).
- Token cache has bounded size (256 entries) and short TTL (30s).

## Why No Unresolved Issues

All findings were localized, high-confidence, and validated within the same review pass:
- Production code fixes (4 files) confirmed by 164 passing unit tests
- Test quality fixes (3 files) replace anti-patterns with behavioral verification
- No architectural decisions were changed
- No requirement scope was modified
- Security review found no issues
- Paradigm-fit verified against existing patterns
