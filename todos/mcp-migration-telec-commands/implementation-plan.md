# Implementation Plan: mcp-migration-telec-commands

## Overview

Add 8 new REST API endpoints and 22 telec CLI subcommands. Add daemon-side
role enforcement. Enrich `telec docs` help text. Write rich `--help` for all
new subcommands. Update telec-cli spec doc with `@exec` directives.

The approach:

1. Role enforcement middleware in the daemon API (checks system_role + human_role).
2. New REST endpoints in resource-scoped router files (sessions, todos, deploy).
3. A shared sync HTTP helper for one-shot CLI calls to the daemon.
4. CLI subcommand handlers extending existing resource groups.
5. Wire into `CLI_SURFACE`, `TelecCommand` enum, and dispatch.
6. Update telec-cli spec doc with `@exec` directives for baseline tools.

CLI structure mirrors REST resources. No invented groupings.

### Key Design Decisions

1. **Resource-scoped routes** — New endpoints sit next to existing ones in their
   resource routers. Session endpoints extend `/sessions/`, todo endpoints go
   in a new `/todos/` router, deploy gets a top-level `POST /deploy`.
2. **Sync HTTP client** — Tool CLI commands are one-shot. `httpx.Client` with
   `HTTPTransport(uds=...)` directly. No async overhead.
3. **JSON to stdout** — All tool subcommands output JSON. Errors to stderr.
4. **Dual-factor identity** — `telec` sends two headers on every API call:
   - `X-Caller-Session-Id`: read from `$TMPDIR/teleclaude_session_id`
   - `X-Tmux-Session`: read from `tmux display-message -p '#S'` (queries tmux server)
     The daemon cross-checks both against its DB before processing any request.
     This prevents session_id forgery — the agent can write to the file but cannot
     control the tmux server's answer about which session it's running in.
5. **Daemon-side role enforcement** — FastAPI dependency reads both headers,
   verifies tmux session matches the claimed session_id in DB, then looks up
   system_role + human_role and checks clearance per endpoint. Returns 403 on
   identity mismatch or insufficient clearance, 401 on missing session_id.
   Replaces MCP wrapper's file-based `role_tools.py` filtering.

### New Endpoints (8 total)

| Resource  | Endpoint                          | Backend Function                            |
| --------- | --------------------------------- | ------------------------------------------- |
| sessions  | `POST /sessions/run`              | `create_session(auto_command=...)`          |
| sessions  | `POST /sessions/{id}/unsubscribe` | `unregister_listener()`                     |
| sessions  | `POST /sessions/{id}/result`      | `client.send_message()`                     |
| sessions  | `POST /sessions/{id}/widget`      | `client.send_widget()`                      |
| sessions  | `POST /sessions/{id}/escalate`    | `DiscordAdapter.create_escalation_thread()` |
| todos     | `POST /todos/prepare`             | `next_prepare()`                            |
| todos     | `POST /todos/work`                | `next_work()`                               |
| todos     | `POST /todos/maintain`            | `next_maintain()`                           |
| todos     | `POST /todos/mark-phase`          | `mark_phase()`                              |
| todos     | `POST /todos/set-deps`            | `set_dependencies()`                        |
| top-level | `POST /deploy`                    | `redis_transport.send_system_command()`     |

Existing endpoints (15) need only CLI wiring — no API changes.

### CLI Command Mapping

| `telec` command              | REST endpoint                       |
| ---------------------------- | ----------------------------------- |
| `telec sessions list`        | `GET /sessions`                     |
| `telec sessions start`       | `POST /sessions`                    |
| `telec sessions send`        | `POST /sessions/{id}/message`       |
| `telec sessions tail`        | `GET /sessions/{id}/messages`       |
| `telec sessions run`         | `POST /sessions/run`                |
| `telec sessions end`         | `DELETE /sessions/{id}`             |
| `telec sessions unsubscribe` | `POST /sessions/{id}/unsubscribe`   |
| `telec sessions result`      | `POST /sessions/{id}/result`        |
| `telec sessions file`        | `POST /sessions/{id}/file`          |
| `telec sessions widget`      | `POST /sessions/{id}/widget`        |
| `telec sessions escalate`    | `POST /sessions/{id}/escalate`      |
| `telec todo prepare`         | `POST /todos/prepare`               |
| `telec todo work`            | `POST /todos/work`                  |
| `telec todo maintain`        | `POST /todos/maintain`              |
| `telec todo mark-phase`      | `POST /todos/mark-phase`            |
| `telec todo set-deps`        | `POST /todos/set-deps`              |
| `telec computers`            | `GET /computers`                    |
| `telec projects`             | `GET /projects`                     |
| `telec deploy`               | `POST /deploy`                      |
| `telec agents status`        | `POST /agents/{agent}/status`       |
| `telec agents availability`  | `GET /agents/availability`          |
| `telec channels list`        | `GET /api/channels/`                |
| `telec channels publish`     | `POST /api/channels/{name}/publish` |

---

## Phase 1: Role Enforcement Middleware

### Task 1.1: Create dual-factor identity verification

**File(s):** `teleclaude/api/auth.py` (new)

A FastAPI dependency that verifies caller identity and checks role clearance:

```python
from fastapi import Header, HTTPException

async def verify_caller(
    x_caller_session_id: str | None = Header(None),
    x_tmux_session: str | None = Header(None),
) -> CallerIdentity:
    """Verify caller identity via dual-factor check.

    Factor 1: session_id from $TMPDIR/teleclaude_session_id (file, writable)
    Factor 2: tmux session name from tmux server (unforgeable)

    Both must agree with the daemon's DB records.
    """
    if not x_caller_session_id:
        raise HTTPException(401, "session identity required")

    session = await db.get_session(x_caller_session_id)
    if not session:
        raise HTTPException(401, "unknown session")

    # Cross-check: tmux session name must match DB record
    if x_tmux_session and session.tmux_session_name:
        if x_tmux_session != session.tmux_session_name:
            raise HTTPException(403, "session identity mismatch")

    return CallerIdentity(
        session_id=x_caller_session_id,
        system_role=session.system_role,
        human_role=session.human_role,
    )

def require_clearance(system_min: str | None = None,
                      human_min: str | None = None):
    """Endpoint dependency that checks role clearance."""
    ...
```

Enforcement order:

1. Missing session_id → 401
2. Unknown session_id → 401
3. Tmux session mismatch → 403 (hijack attempt)
4. Insufficient system_role → 403
5. Insufficient human_role → 403
6. All clear → proceed

- [x] Create `teleclaude/api/auth.py` with `verify_caller` dependency
- [x] Create `CallerIdentity` dataclass (session_id, system_role, human_role)
- [x] Implement `require_clearance` dependency with permission matrix
- [x] Return 403 on identity mismatch with "session identity mismatch" message
- [x] Return 403 on insufficient clearance with specific role/command in message
- [x] Return 401 on missing or unknown session_id
- [x] Store system_role on session records (extend DB schema if needed)
- [x] Write unit tests for:
  - Permission matrix (all cells in the matrix from parent requirements)
  - Tmux cross-check pass (matching tmux session name)
  - Tmux cross-check fail (mismatched tmux session name → 403)
  - Missing session_id → 401
  - Unknown session_id → 401
  - Graceful fallback when tmux header is absent (non-tmux callers like TUI)

---

## Phase 2: REST API Endpoints

### Task 2.1: Session endpoints

**File(s):** `teleclaude/api_server.py` (extend existing session routes)

- [x] Add `POST /sessions/run` (run-agent-command)
- [x] Add `POST /sessions/{id}/unsubscribe` (stop-notifications)
- [x] Add `POST /sessions/{id}/result` (send-result)
- [x] Add `POST /sessions/{id}/widget` (render-widget)
- [x] Add `POST /sessions/{id}/escalate` (escalate)
- [x] Apply role enforcement dependency to all session endpoints

### Task 2.2: Todo/workflow endpoints

**File(s):** `teleclaude/api/todo_routes.py` (new router)

- [x] Add `POST /todos/prepare` (next-prepare state machine)
- [x] Add `POST /todos/work` (next-work state machine)
- [x] Add `POST /todos/maintain` (next-maintain)
- [x] Add `POST /todos/mark-phase` (mark phase completion)
- [x] Add `POST /todos/set-deps` (set dependencies)
- [x] Mount router in `api_server.py`
- [x] Apply role enforcement

### Task 2.3: Deploy endpoint

**File(s):** `teleclaude/api_server.py` (add top-level route)

- [x] Add `POST /deploy` (trigger deployment to remote computers)
- [x] Apply role enforcement (admin-only)

### Task 2.4: Apply role enforcement to existing endpoints

- [x] Add enforcement dependency to existing session endpoints
- [x] Add enforcement dependency to existing computer/project endpoints
- [x] Add enforcement dependency to existing agent endpoints
- [x] Add enforcement dependency to existing channel endpoints

---

## Phase 3: CLI Tool Client

### Task 3.1: Create synchronous tool client with dual-factor identity

**File(s):** `teleclaude/cli/tool_client.py` (new)

```python
import subprocess
import httpx

def tool_api_call(method: str, path: str, json=None, params=None) -> dict:
    session_id = _read_caller_session_id()
    tmux_session = _read_tmux_session_name()
    headers = {}
    if session_id:
        headers["x-caller-session-id"] = session_id
    if tmux_session:
        headers["x-tmux-session"] = tmux_session
    transport = httpx.HTTPTransport(uds=API_SOCKET_PATH)
    with httpx.Client(transport=transport, base_url="http://localhost",
                      timeout=30.0) as client:
        resp = client.request(method, path, json=json, params=params,
                              headers=headers)
        resp.raise_for_status()
        return resp.json()

def _read_caller_session_id() -> str | None:
    """Read session_id from $TMPDIR/teleclaude_session_id."""
    ...

def _read_tmux_session_name() -> str | None:
    """Query tmux server for current session name.

    Uses `tmux display-message -p '#S'` which asks the tmux server
    process — not an env var. The agent cannot forge this value.
    Returns None if not running inside tmux.
    """
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None
```

- [x] Create `teleclaude/cli/tool_client.py`
- [x] Implement `tool_api_call()` with sync httpx + Unix socket transport
- [x] Implement `_read_caller_session_id()` from `$TMPDIR`
- [x] Implement `_read_tmux_session_name()` via tmux server query
- [x] Send both `X-Caller-Session-Id` and `X-Tmux-Session` headers
- [x] Handle daemon unavailable (socket missing → stderr + exit 1)
- [x] Handle 401 (missing/unknown session → stderr + exit 1)
- [x] Handle 403 (identity mismatch or role denied → stderr + exit 1)
- [x] Handle other HTTP errors (4xx/5xx → stderr + exit 1)
- [x] Graceful when not inside tmux (omit header, daemon skips cross-check)

---

## Phase 4: CLI Subcommand Handlers with Rich Help

### Task 4.1: Extend sessions subcommands

**File(s):** `teleclaude/cli/tool_commands.py` (new)

Add handlers for: list, start, send, tail, run, end, unsubscribe, result, file, widget, escalate

Each handler parses flags, calls `tool_api_call()`, prints JSON to stdout.
Rich `--help` with behavioral guidance from MCP tool descriptions.

- [x] Implement sessions subcommand handlers (11 subcommands)
- [x] Rich `--help` for each with examples

### Task 4.2: Extend todo subcommands

**File(s):** `teleclaude/cli/tool_commands.py`

Add handlers for: prepare, work, maintain, mark-phase, set-deps
(extends existing `telec todo` group)

- [x] Implement todo workflow subcommand handlers (5 subcommands)
- [x] Rich `--help` for each

### Task 4.3: Add top-level and new group commands

**File(s):** `teleclaude/cli/tool_commands.py`

Add: computers, projects, deploy, agents (status + availability), channels (list + publish)

- [x] Implement top-level command handlers (computers, projects, deploy)
- [x] Implement agents group handlers (status, availability)
- [x] Implement channels group handlers (list, publish)
- [x] Rich `--help` for each

### Task 4.4: Wire into CLI surface

**File(s):** `teleclaude/cli/telec.py`

- [x] Add new `CommandDef` entries to `CLI_SURFACE` for sessions subcommands
- [x] Add `CommandDef` entries for new todo subcommands (extend existing)
- [x] Add `CommandDef` entries for computers, projects, deploy
- [x] Add `CommandDef` for agents group
- [x] Add `CommandDef` for channels group
- [x] Add dispatch cases in `_handle_cli_command()`
- [x] Update completions

### Task 4.5: Remove legacy aliases

**File(s):** `teleclaude/cli/telec.py`

- [x] Remove `CLAUDE`, `GEMINI`, `CODEX`, `LIST` from `TelecCommand`
- [x] Remove their `CLI_SURFACE` entries and dispatch cases
- [x] Remove `_quick_start()` and related functions
- [x] Remove `_complete_agent()` completion handler

---

## Phase 5: Spec Doc + Validation

### Task 5.1: Update telec-cli spec doc

**File(s):** `docs/global/general/spec/tools/telec-cli.md`

- [x] Add `@exec` directives for baseline tools
- [x] Run `telec sync` to verify expansion
- [x] Verify expanded output includes rich help with examples

### Task 5.2: Functional tests

- [x] Test each new CLI subcommand returns valid JSON
- [x] Test role enforcement returns 403 for worker calling `sessions start`
- [x] Test role enforcement returns 401 for missing session_id
- [x] Test daemon down → graceful error

### Task 5.3: Regression tests

- [x] Run `make lint` and `make test`
- [x] Verify existing commands unaffected
- [x] Verify TUI still works
- [x] Verify `telec --help` shows correct structure

---

## File Summary

| File                              | Action  | Purpose                                       |
| --------------------------------- | ------- | --------------------------------------------- |
| `teleclaude/api/auth.py`          | **new** | Role enforcement dependency                   |
| `teleclaude/api/todo_routes.py`   | **new** | Todo/workflow REST endpoints                  |
| `teleclaude/cli/tool_client.py`   | **new** | Sync HTTP client for CLI                      |
| `teleclaude/cli/tool_commands.py` | **new** | CLI subcommand handlers                       |
| `teleclaude/api_server.py`        | modify  | New session + deploy endpoints, mount routers |
| `teleclaude/cli/telec.py`         | modify  | CLI surface, dispatch, completions            |
| `docs/.../telec-cli.md`           | modify  | Add @exec directives                          |

## Scope Note

4 new files + 3 modifications. Natural split if context pressure:
Phase 1-3 (auth + API + client) as one session, Phase 4-5 (CLI + help +
validation) as a second.
