# Implementation Plan: mcp-migration-tc-cli

## Overview

Add a JSON-RPC endpoint to the daemon API server and extend the `telec` CLI with
tool subcommand groups. This creates the invocation backbone for all tool specs,
replacing MCP as the tool call mechanism.

The approach: add `/rpc` route on the existing FastAPI server that delegates to
the same backend functions the MCP handlers use, then add `telec` subcommands
that call `/rpc` via httpx on the Unix socket.

### Key Design Decisions

1. **Single `/rpc` endpoint** — not 24 new REST endpoints. One route, one method
   router. Keeps the API surface minimal and mirrors the MCP dispatch pattern.
2. **Nested CLI dispatch** — add group enum values (`SESSIONS`, `WORKFLOW`, etc.)
   to `TelecCommand`, each dispatching to a group handler that parses subcommands.
   No framework change (still custom enum dispatch).
3. **Direct backend calls** — the RPC handler imports and calls the same functions
   as MCP handlers (`command_handlers.*`, `get_command_service().*`, `next_prepare`,
   etc.), not the MCP mixin methods. Clean separation from MCP.
4. **`telec docs` unchanged** — tool specs are doc snippets indexed by `telec sync`.
   `telec docs` already serves them via `build_context_output`. No extension needed.

### Method Mapping (24 tools → RPC methods)

| Group          | RPC Method                    | Backend Function                            |
| -------------- | ----------------------------- | ------------------------------------------- |
| context        | `context.query`               | `build_context_output()`                    |
| context        | `context.help`                | static text                                 |
| sessions       | `sessions.list`               | `command_handlers.list_sessions()`          |
| sessions       | `sessions.create`             | `get_command_service().create_session()`    |
| sessions       | `sessions.message`            | `get_command_service().process_message()`   |
| sessions       | `sessions.data`               | `get_command_service().get_session_data()`  |
| sessions       | `sessions.command`            | `create_session(auto_command=...)`          |
| sessions       | `sessions.stop-notifications` | `unregister_listener()`                     |
| sessions       | `sessions.end`                | `command_handlers.end_session()`            |
| workflow       | `workflow.prepare`            | `next_prepare()`                            |
| workflow       | `workflow.work`               | `next_work()`                               |
| workflow       | `workflow.maintain`           | `next_maintain()`                           |
| workflow       | `workflow.mark-phase`         | `mark_phase()`                              |
| workflow       | `workflow.set-deps`           | `read/write_dependencies()`                 |
| infrastructure | `infra.computers`             | `command_handlers.get_computer_info()`      |
| infrastructure | `infra.projects`              | `command_handlers.list_projects()`          |
| infrastructure | `infra.deploy`                | `redis_transport.send_system_command()`     |
| infrastructure | `infra.agent-status`          | `db.mark_agent_*()`                         |
| delivery       | `delivery.result`             | `client.send_message()`                     |
| delivery       | `delivery.file`               | `client.send_file()`                        |
| delivery       | `delivery.widget`             | `client.send_message()` + widget render     |
| delivery       | `delivery.escalate`           | `DiscordAdapter.create_escalation_thread()` |
| channels       | `channels.publish`            | `publish()`                                 |
| channels       | `channels.list`               | `list_channels()`                           |

---

## Phase 1: JSON-RPC Endpoint

### Task 1.1: Create RPC route module

**File(s):** `teleclaude/api/tool_rpc.py` (new)

Create a FastAPI router with a single `POST /rpc` endpoint that:

- Accepts JSON-RPC 2.0 requests: `{"method": "sessions.list", "params": {...}, "id": 1}`
- Routes method names via a dispatch dict (same pattern as `mcp_server.py:617-643`)
- Extracts `caller_session_id` from `X-Caller-Session-Id` header
- Returns JSON-RPC 2.0 responses: `{"result": ..., "id": 1}` or `{"error": {...}, "id": 1}`
- Pydantic model for request/response validation

Key implementation details:

- Method router is a dict mapping string method names to async handler coroutines
- Each handler receives `params: dict` and `caller_session_id: str | None`
- Handlers call backend functions directly (import from `teleclaude.core.*`)
- Error codes: -32600 (invalid request), -32601 (method not found), -32602 (invalid params), -32603 (internal error)

```python
# Pseudocode for the router structure
rpc_router = APIRouter()

@rpc_router.post("/rpc")
async def handle_rpc(request: RpcRequest, raw_request: Request) -> RpcResponse:
    caller_session_id = raw_request.headers.get("x-caller-session-id")
    handler = METHOD_REGISTRY.get(request.method)
    if not handler:
        return RpcError(code=-32601, message=f"Unknown method: {request.method}")
    result = await handler(request.params or {}, caller_session_id)
    return RpcResponse(result=result, id=request.id)
```

- [ ] Create `teleclaude/api/tool_rpc.py` with `APIRouter`
- [ ] Define `RpcRequest` and `RpcResponse` Pydantic models
- [ ] Implement method dispatch dict for all 24 methods
- [ ] Each method handler extracts typed params and calls backend functions
- [ ] Error handling: catch exceptions, return JSON-RPC error responses

### Task 1.2: Mount RPC router on API server

**File(s):** `teleclaude/api_server.py`

- [ ] Import `rpc_router` from `teleclaude.api.tool_rpc`
- [ ] Add `self.app.include_router(rpc_router)` in `__init__` alongside existing routers
- [ ] Pass required dependencies (client, cache, db references) to the router via app state

### Task 1.3: Implement session group handlers

**File(s):** `teleclaude/api/tool_rpc.py`

The sessions group is the largest (7 methods) and most complex. Implement:

- `sessions.list` — calls `command_handlers.list_sessions()`, merges with cache
- `sessions.create` — builds `SessionLaunchIntent`, calls `get_command_service().create_session()` + agent start
- `sessions.message` — calls `get_command_service().process_message()`
- `sessions.data` — calls `get_command_service().get_session_data()`
- `sessions.command` — same as create but with `auto_command` parameter
- `sessions.stop-notifications` — calls `unregister_listener()`
- `sessions.end` — calls `command_handlers.end_session()`

Note: `sessions.create` and `sessions.command` are the most complex — they need
listener registration for AI-to-AI notifications, which requires access to the
MCP handlers' listener logic. Extract `_register_listener_if_present` into a
shared utility or replicate the pattern.

- [ ] Implement all 7 session method handlers
- [ ] Handle local vs. remote branching (same pattern as MCP handlers)
- [ ] Test session CRUD via curl against running daemon

### Task 1.4: Implement remaining group handlers

**File(s):** `teleclaude/api/tool_rpc.py`

Implement the simpler groups:

- **context** (2 methods): `context.query` calls `build_context_output()`, `context.help` returns static text
- **workflow** (5 methods): thin wrappers around `next_prepare/work/maintain`, `mark_phase`, `set_dependencies`
- **infrastructure** (4 methods): calls to `command_handlers`, `redis_transport`, `db`
- **delivery** (4 methods): calls to `client.send_message/send_file`, widget rendering, escalation
- **channels** (2 methods): calls to `publish()` and `list_channels()`

- [ ] Implement context group (2 handlers)
- [ ] Implement workflow group (5 handlers)
- [ ] Implement infrastructure group (4 handlers)
- [ ] Implement delivery group (4 handlers)
- [ ] Implement channels group (2 handlers)

### Task 1.5: Test RPC endpoint

- [ ] Test every method via `curl -X POST --unix-socket /tmp/teleclaude-api.sock http://localhost/rpc`
- [ ] Verify JSON-RPC error responses for invalid method, missing params
- [ ] Verify `caller_session_id` header injection works
- [ ] Verify daemon-down produces no socket (expected — telec will handle this)

---

## Phase 2: telec CLI Subcommand Groups

### Task 2.1: Create RPC client utility

**File(s):** `teleclaude/cli/rpc_client.py` (new)

A lightweight synchronous JSON-RPC client for `telec` subcommands:

```python
def rpc_call(method: str, params: dict | None = None) -> dict:
    """Call daemon RPC endpoint. Returns result dict or raises RPCError."""
    session_id = _read_caller_session_id()  # from $TMPDIR/teleclaude_session_id
    response = httpx.post(
        "http://localhost/rpc",
        transport=httpx.HTTPTransport(uds=API_SOCKET_PATH),
        json={"method": method, "params": params or {}, "id": 1},
        headers={"x-caller-session-id": session_id} if session_id else {},
        timeout=30.0,
    )
    ...
```

- [ ] Create `teleclaude/cli/rpc_client.py`
- [ ] Implement `rpc_call()` with Unix socket transport
- [ ] Read `caller_session_id` from `$TMPDIR/teleclaude_session_id`
- [ ] Graceful error when daemon is unavailable (socket doesn't exist or connection refused)
- [ ] Print errors to stderr, return None or raise
- [ ] JSON output to stdout via `json.dumps(result, indent=2)`

### Task 2.2: Add subcommand group enum values and dispatch

**File(s):** `teleclaude/cli/telec.py`

Add new entries to `TelecCommand` enum and update `_handle_cli_command()`:

```python
class TelecCommand(str, Enum):
    # Existing
    LIST = "list"
    REVIVE = "revive"
    INIT = "init"
    SYNC = "sync"
    WATCH = "watch"
    DOCS = "docs"
    TODO = "todo"
    CONFIG = "config"
    ONBOARD = "onboard"
    # New tool groups
    SESSIONS = "sessions"
    WORKFLOW = "workflow"
    INFRA = "infra"
    DELIVERY = "delivery"
    CHANNELS = "channels"
    DEPLOY = "deploy"  # shortcut for infra.deploy
```

Update `_handle_cli_command()` to dispatch group commands to a handler module.

- [ ] Add new enum values
- [ ] Add dispatch cases in `_handle_cli_command()`
- [ ] Update `_COMMAND_DESCRIPTIONS` dict
- [ ] Update completion definitions

### Task 2.3: Create tool subcommand handlers

**File(s):** `teleclaude/cli/tool_commands.py` (new)

Group handler functions that parse subcommands and call `rpc_call()`:

```python
def handle_sessions(args: list[str]) -> None:
    """Handle telec sessions <subcommand> [options]."""
    if not args or args[0] in ("--help", "-h"):
        print(_sessions_usage())
        return
    subcmd = args[0]
    rest = args[1:]
    if subcmd == "list":
        result = rpc_call("sessions.list", _parse_sessions_list_args(rest))
    elif subcmd == "create":
        result = rpc_call("sessions.create", _parse_sessions_create_args(rest))
    ...
    _print_json(result)
```

Implement handlers for each group:

- `handle_sessions(args)` — list, create, message, data, command, stop-notifications, end
- `handle_workflow(args)` — prepare, work, maintain, mark-phase, set-deps
- `handle_infra(args)` — computers, projects, deploy, agent-status
- `handle_delivery(args)` — result, file, widget, escalate
- `handle_channels(args)` — publish, list
- `handle_deploy(args)` — shortcut for `infra.deploy`

- [ ] Create `teleclaude/cli/tool_commands.py`
- [ ] Implement `handle_sessions()` with all 7 subcommands
- [ ] Implement `handle_workflow()` with all 5 subcommands
- [ ] Implement `handle_infra()` with all 4 subcommands
- [ ] Implement `handle_delivery()` with all 4 subcommands
- [ ] Implement `handle_channels()` with all 2 subcommands
- [ ] Implement `handle_deploy()` shortcut
- [ ] Add `--help` for each group and subcommand
- [ ] All output is JSON to stdout, errors to stderr

---

## Phase 3: CLI Cleanup

### Task 3.1: Remove agent aliases

**File(s):** `teleclaude/cli/telec.py`

- [ ] Remove `CLAUDE`, `GEMINI`, `CODEX` from `TelecCommand` enum
- [ ] Remove their entries from `_COMMAND_DESCRIPTIONS`
- [ ] Remove the dispatch case in `_handle_cli_command()` (lines 392-395)
- [ ] Remove `_quick_start()` function and `_quick_start_via_api()` (only if not used elsewhere)
- [ ] Update `_usage()` help text — remove agent lines, add tool group lines
- [ ] Update shell completion definitions

### Task 3.2: Update existing `telec list` to use RPC

**File(s):** `teleclaude/cli/telec.py`

The existing `telec list` command uses `TelecAPIClient.list_sessions()` (REST).
Update it to use `rpc_call("sessions.list")` for consistency, or keep it as-is
since it already works. Decision: **keep as-is** — it's a TUI-oriented human
command that shows formatted output, not JSON. The new `telec sessions list` is
the JSON-for-agents version.

- [ ] Verify `telec list` still works unchanged
- [ ] Add note in help text: "`telec list` = human-friendly, `telec sessions list` = JSON"

---

## Phase 4: Validation

### Task 4.1: Functional tests

- [ ] Test every `telec sessions` subcommand against running daemon
- [ ] Test every `telec workflow` subcommand
- [ ] Test every `telec infra` subcommand
- [ ] Test `telec deploy` shortcut
- [ ] Test `telec delivery result` and `telec delivery file`
- [ ] Test `telec channels list` and `telec channels publish`
- [ ] Verify JSON output is valid and parseable

### Task 4.2: Error handling tests

- [ ] Test with daemon down (socket doesn't exist): clear error, exit code 1
- [ ] Test with invalid subcommand: help text shown
- [ ] Test with missing required params: error message to stderr
- [ ] Test caller_session_id injection (set env var, verify header sent)

### Task 4.3: Regression tests

- [ ] Run `make lint`
- [ ] Run `make test`
- [ ] Verify `telec sync`, `telec init`, `telec docs`, `telec todo`, `telec config` unchanged
- [ ] Verify `telec list` still works (human-friendly output)
- [ ] Verify `telec --help` shows updated command list

---

## File Summary

| File                              | Action  | Purpose                                         |
| --------------------------------- | ------- | ----------------------------------------------- |
| `teleclaude/api/tool_rpc.py`      | **new** | JSON-RPC endpoint with method dispatch          |
| `teleclaude/cli/rpc_client.py`    | **new** | Synchronous RPC client for telec commands       |
| `teleclaude/cli/tool_commands.py` | **new** | Subcommand group handlers                       |
| `teleclaude/api_server.py`        | modify  | Mount RPC router                                |
| `teleclaude/cli/telec.py`         | modify  | New enum values, dispatch, remove agent aliases |

## Integration Notes

- MCP server continues running in parallel — no disruption during migration
- Downstream todos (`context-integration`, `agent-config`) will wire these
  subcommands into agent sessions and update tool spec docs
- The `telec-cli` tool spec in CLAUDE.md baseline will need revision after
  this work lands (handled by `mcp-migration-doc-updates`)
