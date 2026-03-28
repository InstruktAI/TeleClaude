# edge-http-migration — Implementation Plan

## Overview

Migrate three daemon-internal session creation callers from direct `CommandService`
calls to HTTP requests through the API edge layer, provision daemon self-authentication,
and remove the dead `run_slash_command` method. After this change, every session
creation flows through the edge, which assembles `origin_metadata` and runs identity
resolution.

Three phases: infrastructure (internal HTTP client + auth), migration (three callers),
cleanup (dead code removal).

---

## Phase 1: Infrastructure

### Task 1.1: Create daemon-internal HTTP client (R1, R2)

**What:** A thin async helper module that daemon-internal code calls instead of
`CommandService` directly. It issues HTTP requests to the daemon's own API over the
Unix domain socket, authenticated with a session token.

**Why:** All three callers need the same plumbing — an authenticated async httpx call
over UDS to `POST /sessions` or `POST /sessions/run`. Centralizing avoids duplicating
transport and auth logic. The pattern exists in `teleclaude/cli/tool_client.py` (sync)
and `teleclaude/cli/api_client.py` (async) but those are CLI-side with CLI-specific
identity resolution. The daemon-internal client is simpler: only `X-Session-Token`
auth, using the known `API_SOCKET_PATH` from `teleclaude/constants.py`.

**Files:**

- Create `teleclaude/core/internal_api_client.py`

The module exposes two async functions:

- `run_session(command, project, *, args, detach, agent, thinking_mode)` — maps to
  `POST /sessions/run` with `RunSessionRequest` body
- `create_session(project_path, *, title, auto_command, origin, origin_metadata, metadata)` — maps to `POST /sessions` with `CreateSessionRequest` body

Both accept a `token` parameter (or read from module-level state set at daemon startup).
Both return the JSON response dict.

**Verification:**

- Remove xfail from `tests/unit/core/test_internal_api_client.py::test_run_session_sends_correct_request`
  and `test_create_session_sends_correct_request` — verify the client sends correct
  HTTP method, path, JSON body, and `X-Session-Token` header. Mock httpx at the
  transport layer.

---

### Task 1.2: Daemon system session and token provisioning (R2)

**What:** At daemon startup, create (or reuse) a lightweight system session that
represents the daemon process itself. Issue a session token for it. Pass the token to
the internal API client from Task 1.1.

**Why:** The API auth middleware (`teleclaude/api/auth.py`) resolves identity from
`X-Session-Token` via `_verify_token_identity`. The token produces a `CallerIdentity`
with `session_id` (required by `POST /sessions/run`), `system_role`, and clearance.
The token issuance pattern exists: `daemon_session.py:72` issues tokens for
`system:` principals via `db.issue_session_token`.

**Files:**

- Modify `teleclaude/daemon.py` — after API server startup, create the daemon system
  session and issue a token; pass it to the internal API client
- Possibly modify `teleclaude/core/internal_api_client.py` — add `configure(token)`
  to store the token for reuse

**Approach:** The daemon session is created with:

- `system_role="system"`, `job=None`
- `title="daemon-service"` (or similar identifier)
- `principal="system:daemon"`, `role="system"`

The session persists across daemon restarts via the DB. On startup, the daemon looks
for an existing daemon-service session; if found and active, reuses it. If not, creates
a new one. A fresh token is always issued (tokens have TTL via the ledger).

**Verification:**

- Remove xfail from `tests/unit/core/test_internal_api_client.py::test_daemon_token_provisioning` —
  verify the daemon session creation flow produces a session with `system_role="system"`
  and issues a token.
- Remove xfail from `tests/unit/core/test_internal_api_client.py::test_token_identity_has_valid_clearance` —
  verify `_verify_token_identity` with the daemon token produces a `CallerIdentity`
  with valid `session_id` and appropriate clearance for `POST /sessions/run` and
  `POST /sessions`.

---

## Phase 2: Migration

### Task 2.1: Migrate integration bridge to HTTP (R1, R5)

**What:** Replace `get_command_service().run_slash_command(SlashCommand.NEXT_INTEGRATE, ...)`
in `teleclaude/core/integration_bridge.py:314` with an internal HTTP client call to
`POST /sessions/run`.

**Why:** First of three callers bypassing the API edge. After migration, the edge
assembles `origin_metadata` and runs identity resolution for every integrator session.

**Files:**

- Modify `teleclaude/core/integration_bridge.py` — replace `run_slash_command` call
  with `internal_api_client.run_session(...)`, remove now-unused imports
  (`CommandMapper`, `MessageMetadata`, `InputOrigin` if unused)
- Modify `tests/unit/core/test_integration_bridge.py` — update spawn tests to verify
  HTTP call instead of `run_slash_command`

**Request mapping:**

```python
await internal_api_client.run_session(
    command="/next-integrate",
    project=project_path,
    detach=True,
)
```

**Behavioral preservation (R5):**

- System role `integrator` and job `integrator` are derived server-side by
  `_prepare_run_session` via `COMMAND_ROLE_MAP` — same derivation path as before.
- `detach=True` maps to `skip_listener_registration=True` in the route handler.
- The `auto_command` is built server-side.

**Verification:**

- Remove xfail from `tests/unit/core/test_integration_bridge.py::test_spawn_uses_http_client` —
  verify `_spawn_integrator_session` issues HTTP POST to `/sessions/run` with correct
  body fields and auth header.
- Verify `run_slash_command` is no longer imported in `integration_bridge.py`.
- Pre-commit hooks pass.

---

### Task 2.2: Migrate prepare cartridge to HTTP (R1, R5)

**What:** Replace `get_command_service().run_slash_command(SlashCommand.NEXT_PREPARE, ...)`
in `teleclaude/events/cartridges/prepare.py:437` with an internal HTTP client call.

**Why:** Same architectural violation as the integration bridge — bypasses edge
identity assembly when dispatching prepare agents.

**Files:**

- Modify `teleclaude/events/cartridges/prepare.py` — replace `run_slash_command` in
  `_dispatch_prepare_agent` with `internal_api_client.run_session(...)`, remove
  now-unused imports (`SlashCommand`, `get_command_service` if unused elsewhere)
- Add dispatch path test in `tests/unit/events/cartridges/test_prepare.py`

**Request mapping:**

```python
await internal_api_client.run_session(
    command="/next-prepare",
    project=project_path,
    args=slug,
    detach=True,
)
```

**Behavioral preservation (R5):**

- System role `orchestrator` and job `prepare_orchestrator` derived server-side.
- `detach=True` preserved.
- Slug passed as `args`.

**Verification:**

- Remove xfail from `tests/unit/events/cartridges/test_prepare.py::test_dispatch_prepare_agent_uses_http` —
  verify `_dispatch_prepare_agent` issues HTTP POST to `/sessions/run` with
  `command="/next-prepare"`, `args=slug`, `detach=True`.
- Verify `run_slash_command` no longer referenced from `prepare.py`.
- Pre-commit hooks pass.

---

### Task 2.3: Migrate WhatsApp handler to HTTP (R1, R5)

**What:** Replace `get_command_service().create_session(create_cmd)` in
`teleclaude/hooks/whatsapp_handler.py:49` with an internal HTTP client call to
`POST /sessions`.

**Why:** Third caller bypassing the edge. After migration, identity resolution runs
for WhatsApp sessions.

**Files:**

- Modify `teleclaude/api_models.py` — add `origin` and `origin_metadata` fields to
  `CreateSessionRequest` for daemon-internal origin propagation
- Modify `teleclaude/api/sessions_routes.py` — in `_prepare_create_session`, when
  `request.origin` is set, use it directly instead of deriving from identity context
- Modify `teleclaude/hooks/whatsapp_handler.py` — replace direct service call in
  `_resolve_or_create_session` with `internal_api_client.create_session(...)`, remove
  now-unused imports (`CreateSessionCommand`, `get_command_service` for session
  creation path)
- Update `tests/unit/hooks/test_whatsapp_handler.py` if tests touch the creation path

**Origin propagation — chosen path:**

The `POST /sessions` route currently derives origin from identity context (terminal
vs web via `request.human_email`). For daemon-internal WhatsApp session creation, the
handler must propagate `origin=whatsapp` and `origin_metadata={"phone_number": ...,
"platform": "whatsapp"}` through the API request.

**Approach:** Add explicit optional fields to `CreateSessionRequest`:

```python
origin: str | None = None  # daemon-internal override
origin_metadata: dict[str, object] | None = None  # daemon-internal origin-specific data
```

In `_prepare_create_session`, when `request.origin` is set, use it directly:

```python
if request.origin:
    origin = request.origin
    typed_origin = request.origin_metadata  # pass through as-is
elif request.human_email:
    origin = InputOrigin.WEB.value
    typed_origin = WebOriginMetadata(email=caller_email)
else:
    origin = InputOrigin.TERMINAL.value
    typed_origin = TerminalOriginMetadata(email=caller_email) if caller_email else None
```

**Why this approach, not `metadata` dict smuggling:** The generic `metadata` dict on
`CreateSessionRequest` is consumed by `_extract_session_role_fields` for
`system_role`/`job` only. Repurposing it for origin data would conflate two different
concerns in one untyped dict. Explicit fields are self-documenting, type-checked, and
align with `CreateSessionCommand` which already has `origin` and `origin_metadata`
fields. Backward compatible — existing callers don't set these fields, so
identity-derived behavior is unchanged.

**Request mapping:**

```python
result = await internal_api_client.create_session(
    project_path=config.computer.help_desk_dir,
    title=f"WhatsApp: {phone_number}",
    auto_command=f"agent {get_default_agent()}",
    origin=InputOrigin.WHATSAPP.value,
    origin_metadata={
        "phone_number": phone_number,
        "platform": "whatsapp",
    },
)
session_id = result.get("session_id")
```

**Behavioral preservation (R5):**

- Phone number lookup via `db.get_sessions_by_origin_metadata` runs before creation
  and is unchanged.
- New sessions carry correct origin, origin_metadata, and agent.
- Adapter dispatch path (`_dispatch_whatsapp_command`) is out of scope.

**Verification:**

- Remove xfail from `tests/unit/hooks/test_whatsapp_handler.py::test_create_session_uses_http_with_origin` —
  verify `_resolve_or_create_session` calls the internal HTTP client with
  `origin="whatsapp"` and `origin_metadata` containing `phone_number`.
- Remove xfail from `tests/unit/api/test_sessions_routes.py::test_create_session_explicit_origin_propagation` —
  verify `_prepare_create_session` uses `request.origin` when set instead of
  deriving from identity.
- Verify `session_id` is correctly extracted from the response.
- Pre-commit hooks pass.

---

## Phase 3: Cleanup

### Task 3.1: Remove `run_slash_command` from CommandService (R3, R6)

**What:** Delete `CommandService.run_slash_command` (lines 357-393 of
`teleclaude/core/command_service.py`) and remove its now-unused imports.

**Why:** All callers are migrated. Dead code violates code quality policy.

**Files:**

- Modify `teleclaude/core/command_service.py` — delete `run_slash_command` method,
  clean unused imports (`shlex`, `CommandMapper`, `MessageMetadata`, `InputOrigin` —
  only those that become unused after deletion)
- Modify `tests/unit/core/test_integration_bridge.py` — remove the three
  `test_run_slash_command_*` tests that directly test the deleted method

**Constraint (R6):** `COMMAND_ROLE_MAP` must remain defined and exported. It is
imported by `teleclaude/api/sessions_actions_routes.py:54`. Do not remove it.

**Verification:**

- Remove xfail from `tests/unit/core/test_command_service.py::test_run_slash_command_removed` —
  verify `run_slash_command` is not an attribute of `CommandService`.
- `COMMAND_ROLE_MAP` is still imported and used by `sessions_actions_routes.py`.
- Pre-commit hooks pass.

---

## Risks

- **POST /sessions/run requires caller session_id:** Mitigated by Task 1.2 — the
  daemon system session token produces a valid `CallerIdentity`.

- **WhatsApp origin propagation:** Mitigated by the explicit `origin`/`origin_metadata`
  fields on `CreateSessionRequest` (Task 2.3). The `_prepare_create_session` function
  uses the request fields when present, falls back to identity-derived origin when absent.

- **Concurrent sessions during migration:** Not a runtime migration — no risk. All
  sessions created after deployment use the new path.

## Dependencies

None. This todo has no prerequisites in the roadmap.
