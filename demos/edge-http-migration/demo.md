# Demo: edge-http-migration

## Validation

```bash
# R1/R3: No production code calls run_slash_command or creates sessions via CommandService directly
# (outside the API route handlers)
grep -rn "run_slash_command" teleclaude/ | grep -v "__pycache__" | grep -v ".pyc" && echo "FAIL: run_slash_command still referenced" || echo "PASS: run_slash_command removed"
```

```bash
# R1: Integration bridge uses TelecAPIClient, not CommandService
grep -n "TelecAPIClient\|api_client" teleclaude/core/integration_bridge.py && echo "PASS: uses edge HTTP client" || echo "FAIL: not migrated"
```

```bash
# R1: Prepare cartridge uses TelecAPIClient, not CommandService
grep -n "TelecAPIClient\|api_client" teleclaude/events/cartridges/prepare.py && echo "PASS: uses edge HTTP client" || echo "FAIL: not migrated"
```

```bash
# R1: WhatsApp handler uses TelecAPIClient, not CommandService.create_session
grep -n "TelecAPIClient\|api_client" teleclaude/hooks/whatsapp_handler.py && echo "PASS: uses edge HTTP client" || echo "FAIL: not migrated"
```

```bash
# R2: Daemon system session token provisioned at startup
grep -n "issue_session_token\|daemon.service\|system:daemon" teleclaude/daemon.py && echo "PASS: daemon token provisioned" || echo "FAIL: missing"
```

```bash
# R6: COMMAND_ROLE_MAP still defined and used
grep -n "COMMAND_ROLE_MAP" teleclaude/core/command_service.py teleclaude/api/sessions_actions_routes.py && echo "PASS: COMMAND_ROLE_MAP in use" || echo "FAIL: missing"
```

```bash
# Quality gate: all tests pass
make test 2>&1 | tail -5
```

```bash
# Quality gate: lint and typecheck pass
make lint 2>&1 | tail -5
```

## Guided Presentation

### Step 1: Architecture verification — edge-only session creation

Show that no production code creates sessions by calling `CommandService` methods
directly from outside the API route handlers.

**What to do:** Run `grep -rn "\.create_session\|run_slash_command" teleclaude/ --include="*.py"` and filter out the API route handlers and the `CommandService` class itself.

**What to observe:** Zero hits from `integration_bridge.py`, `prepare.py`, or
`whatsapp_handler.py`.

**Why it matters:** The edge layer now assembles `origin_metadata` and runs identity
resolution for every session creation, including daemon-internal ones.

### Step 2: Reused TelecAPIClient boundary and daemon self-auth

Show that the daemon authenticates with its own API using a session token through
the existing `TelecAPIClient` boundary.

**What to do:** Open `teleclaude/cli/api_client.py` and show the `TelecAPIClient`
class with its identity-header support (`X-Session-Token`). Show the daemon startup
code where the system session is created and the token is issued.

**What to observe:** The `TelecAPIClient` sends `X-Session-Token` on every request
via `_build_identity_headers`. The daemon creates a system session at startup and
issues a fresh token.

**Why it matters:** R2 — no auth bypass. The daemon authenticates through the same
middleware as every other caller, using the same client boundary already tested in
`tests/unit/cli/test_api_client.py`.

### Step 3: WhatsApp origin propagation

Show that WhatsApp sessions carry correct origin data through the edge.

**What to do:** Open `teleclaude/hooks/whatsapp_handler.py` and show the
`TelecAPIClient.create_session()` call with `origin="whatsapp"` and
`origin_metadata`.

**What to observe:** The `TelecAPIClient` passes `origin` and `origin_metadata`
through the `POST /sessions` request body.

**Why it matters:** R5 — WhatsApp sessions flow through the edge with the same origin
data as before.

### Step 4: Test suite passes

**What to do:** Run `make test`.

**What to observe:** All tests pass, including updated tests for the three migrated
callers.

**Why it matters:** R5 — behavioral preservation verified.
