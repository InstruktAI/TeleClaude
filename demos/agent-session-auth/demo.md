# Demo: agent-session-auth

## Overview

Demonstrates the token-based credential system for agent sessions:
principal resolution, token issuance, auth middleware validation,
and revocation on session close.

---

## Section 1: Token DB operations and principal resolution

Run the unit tests that cover the ledger contract.

```bash
pytest tests/unit/test_session_tokens.py -v --tb=short
```

Expected: all 11 tests pass. Covers `issue_session_token`, `validate_session_token`,
`revoke_session_tokens`, and `resolve_session_principal` for both human and system principals.

---

## Section 2: Auth middleware tests

Run the auth middleware tests to confirm token path and clearance checks.

```bash
pytest tests/unit/test_api_auth.py -v --tb=short
```

Expected: all 11 tests pass. Covers `verify_caller()` accepting a valid token,
rejecting invalid/revoked tokens with 401, token priority over session-id path,
and `CallerIdentity.principal` / `principal_role` population.

---

## Section 3: Principal inheritance tests

Run the inheritance tests to confirm the agent chain propagates identity.

```bash
pytest tests/unit/test_principal_inheritance.py -v --tb=short
```

Expected: all 8 tests pass. Covers channel_metadata threading, parent session
principal inheritance, and daemon bootstrap reuse of inherited principal.

---

## Section 4: Full lifecycle tests

Run the lifecycle tests to confirm bootstrap → auth → revoke → reject flow.

```bash
pytest tests/unit/test_session_token_lifecycle.py -v --tb=short
```

Expected: all 8 tests pass. Covers token issuance, live token auth passing,
and post-close rejection in the auth middleware.

---

## Section 5: Full unit suite

Confirm no regressions across the full unit test suite.

```bash
make test-unit
```

Expected: 162+ tests pass.

---

## Section 6: Token ledger schema present

Confirm the `session_tokens` table definition exists in the schema.

```bash
grep -A 10 "CREATE TABLE IF NOT EXISTS session_tokens" teleclaude/core/schema.sql
```

Expected: table definition with `token`, `session_id`, `principal`, `role`,
`issued_at`, `expires_at`, `revoked_at` columns.

---

## Section 7: Confirm principal field on sessions table

```bash
grep "principal" teleclaude/core/schema.sql
```

Expected: `principal TEXT` column visible in sessions table definition
and `session_tokens` table.

---

## Section 8: Confirm migrations exist

```bash
ls teleclaude/core/migrations/ | grep -E "031|032"
```

Expected: `031_add_session_tokens.py` and `032_add_session_principal.py`.

---

## Section 9: Confirm token path in auth middleware

```bash
grep -n "x_session_token\|TELEC_SESSION_TOKEN" teleclaude/api/auth.py teleclaude/cli/api_client.py
```

Expected: `x_session_token` header parameter in `auth.py` and token reading
in `api_client.py`'s `_build_identity_headers`.

---

## Section 10: Confirm revocation in session cleanup

```bash
grep -n "revoke_session_tokens\|invalidate_token_cache" teleclaude/core/session_cleanup.py
```

Expected: both calls present in `_terminate_session_inner`.

---

## Cleanup

No cleanup needed — all tests use mocked state, no real DB or daemon.
