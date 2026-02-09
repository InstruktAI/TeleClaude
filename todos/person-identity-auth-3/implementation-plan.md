# Implementation Plan: Person Identity Auth — Phase 3

## Objective

Wire human role gating and adapter identity integration to complete the auth infrastructure.

## Task 1: Human role tool gating

**File:** `teleclaude/mcp/role_tools.py`

Add `HUMAN_ROLE_EXCLUDED_TOOLS` dict and filtering functions parallel to existing AI role filtering.

**Verification:** Unit test for each role level filtering correct tools.

## Task 2: MCP wrapper human identity marker

**File:** `teleclaude/entrypoints/mcp_wrapper.py`

- Add `_read_human_identity_marker()` alongside existing `_read_role_marker()`.
- Read `teleclaude_human_identity` file from session TMPDIR.
- During tool filtering, apply both AI role filter and human role filter.
- Write human identity marker during session creation.

**Verification:** Marker written and read correctly; tools filtered by human role.

## Task 3: Token issuance endpoint

**File:** `teleclaude/api_server.py`

Add `POST /auth/token` endpoint:

- Accepts email (and optional username) from request body.
- Unix socket only — trusted local process.
- Issues signed token via `create_auth_token()`.

**Verification:** Endpoint returns valid token for known email; rejects unknown.

## Task 4: TUI login command

**File:** New command or extension in TUI CLI.

`telec login <email>`:

1. Validate email in people config via identity resolver.
2. Call daemon `POST /auth/token`.
3. Store token at `~/.teleclaude/auth_token`.
4. Subsequent API calls include `Authorization: Bearer <token>`.

**Verification:** Login stores token; authenticated API calls succeed.

## Task 5: Web boundary identity normalization

**Files:** Web adapter/proxy integration path.

Ensure `X-TeleClaude-Person-Email`, `X-TeleClaude-Person-Role`, optional `X-TeleClaude-Person-Username` headers are normalized to internal metadata before authorization and session binding.

**Verification:** Headers mapped consistently to session metadata.

## Task 6: Integration tests

**File:** `tests/integration/test_identity_integration.py`

- Full flow: config → resolver → session creation with binding.
- Header-based auth: email/role headers → session has identity.
- Token issuance → API call with token → middleware resolves identity.
- Child session inherits parent identity.
- Role gating: restricted tools blocked for contributor/newcomer.

## Files Changed

| File                                             | Change                      |
| ------------------------------------------------ | --------------------------- |
| `teleclaude/mcp/role_tools.py`                   | Add human role filtering    |
| `teleclaude/entrypoints/mcp_wrapper.py`          | Add human identity marker   |
| `teleclaude/api_server.py`                       | Add token issuance endpoint |
| TUI CLI                                          | Add login command           |
| `tests/integration/test_identity_integration.py` | New integration tests       |

## Risks

1. **Strict auth rollout** — existing MCP/TUI clients must propagate identity or they'll be rejected. Migration plan needed.
2. **Header trust boundary** — identity headers must only be accepted from trusted web boundary.

## Verification

- All tests pass.
- Full identity flow works end-to-end.
- Role gating blocks expected operations.
