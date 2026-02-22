# Implementation Plan: mcp-migration-telec-commands

## Overview

Add 12 new REST API endpoints and 22 telec CLI subcommands. Enrich `telec docs`
help text. Write rich `--help` for all new subcommands with behavioral guidance
and examples. Update the telec-cli spec doc with `@exec` directives for
baseline tools. The approach:

1. New REST endpoints in a separate FastAPI router (`teleclaude/api/tool_routes.py`)
   to avoid bloating `api_server.py` further. Each endpoint is a thin wrapper around
   existing backend functions (same ones MCP handlers call).
2. A shared sync HTTP helper (`teleclaude/cli/tool_client.py`) for one-shot CLI calls
   to the daemon — simpler than the async `TelecAPIClient` which is designed for the TUI.
3. CLI subcommand handlers in `teleclaude/cli/tool_commands.py`, one handler per group.
   Each handler includes rich `--help` with behavioral guidance migrated from MCP
   tool descriptions and usage examples covering every parameter/input shape.
4. Wire new groups into `CLI_SURFACE`, `TelecCommand` enum, and dispatch.
5. Enrich existing `telec docs --help` with two-phase flow guidance and examples.
6. Update the telec-cli spec doc with `<!-- @exec: telec <cmd> -h -->` for baseline tools.

**No `telec context` group.** `telec docs` already replaces `teleclaude__get_context`
with the same two-phase flow (index without IDs, full content with IDs). The naming
"docs" is correct — this is documentation snippets, not generic context. The
`teleclaude__help` tool (TeleClaude capabilities summary) relocates to `telec infra help`.

No new business logic. All work is wiring: REST endpoint → backend function,
CLI subcommand → REST endpoint, help text → `@exec` in spec doc.

### Key Design Decisions

1. **Separate router file** — `api_server.py` is 2,029 lines. Tool endpoints go in
   `teleclaude/api/tool_routes.py` and are mounted via `include_router()`.
2. **Sync HTTP client** — Tool CLI commands are one-shot. No async overhead needed.
   `httpx.Client` with `HTTPTransport(uds=...)` directly.
3. **JSON to stdout** — All tool subcommands output JSON. Errors go to stderr.
   This is distinct from existing human-friendly commands (`telec list`, etc.).
4. **`caller_session_id` injection** — Read from `$TMPDIR/teleclaude_session_id`,
   sent as `X-Caller-Session-Id` header on every API call.
5. **Help text as documentation** — The `--help` output carries the full behavioral
   contract from MCP tool descriptions. Examples cover every parameter and shape.
   The telec-cli spec doc inlines baseline help via `@exec` directives.

### Endpoint Design for the 12 Missing Tools

`telec docs` (get_context + help) needs no REST endpoint — it calls
`build_context_output()` directly. `teleclaude__help` relocates to
`telec infra help` (static text, no endpoint needed).

| Group    | Tool               | REST Endpoint                      | Backend Function                            |
| -------- | ------------------ | ---------------------------------- | ------------------------------------------- |
| sessions | run-agent-command  | `POST /tools/sessions/command`     | `create_session(auto_command=...)`          |
| sessions | stop-notifications | `POST /tools/sessions/unsubscribe` | `unregister_listener()`                     |
| workflow | next-prepare       | `POST /tools/workflow/prepare`     | `next_prepare()`                            |
| workflow | next-work          | `POST /tools/workflow/work`        | `next_work()`                               |
| workflow | next-maintain      | `POST /tools/workflow/maintain`    | `next_maintain()`                           |
| workflow | mark-phase         | `POST /tools/workflow/mark-phase`  | `mark_phase()`                              |
| workflow | set-dependencies   | `POST /tools/workflow/set-deps`    | `set_dependencies()`                        |
| infra    | deploy             | `POST /tools/infra/deploy`         | `redis_transport.send_system_command()`     |
| infra    | mark-agent-status  | `POST /tools/infra/agent-status`   | `db.mark_agent_*()`                         |
| delivery | send-result        | `POST /tools/delivery/result`      | `client.send_message()`                     |
| delivery | render-widget      | `POST /tools/delivery/widget`      | `client.send_message()` + widget render     |
| delivery | escalate           | `POST /tools/delivery/escalate`    | `DiscordAdapter.create_escalation_thread()` |

Channels already have REST endpoints at `/api/channels/` (publish and list).
CLI channels subcommands call these existing endpoints directly.

New endpoints are namespaced under `/tools/` to separate them from
existing TUI-facing endpoints.

### CLI Command Mapping (22 new + `telec docs` existing)

`telec docs` already covers `get_context` (two-phase: index without IDs,
full content with comma-separated IDs). No new CLI command needed for it.

| `telec` subcommand                                  | REST Endpoint                            |
| --------------------------------------------------- | ---------------------------------------- |
| `telec sessions list [--computer ...]`              | `GET /sessions` (existing)               |
| `telec sessions start --computer --project --title` | `POST /sessions` (existing)              |
| `telec sessions send --id --message`                | `POST /sessions/{id}/message` (existing) |
| `telec sessions tail --id [--tail ...]`             | `GET /sessions/{id}/messages` (existing) |
| `telec sessions command --computer --command`       | `POST /tools/sessions/command`           |
| `telec sessions unsubscribe --id`                   | `POST /tools/sessions/unsubscribe`       |
| `telec sessions end --id`                           | `DELETE /sessions/{id}` (existing)       |
| `telec workflow prepare [--slug ...]`               | `POST /tools/workflow/prepare`           |
| `telec workflow work [--slug ...]`                  | `POST /tools/workflow/work`              |
| `telec workflow maintain`                           | `POST /tools/workflow/maintain`          |
| `telec workflow mark-phase --slug --phase --status` | `POST /tools/workflow/mark-phase`        |
| `telec workflow set-deps --slug --after`            | `POST /tools/workflow/set-deps`          |
| `telec infra computers`                             | `GET /computers` (existing)              |
| `telec infra projects --computer`                   | `GET /projects` (existing)               |
| `telec infra deploy [--computers ...]`              | `POST /tools/infra/deploy`               |
| `telec infra agent-status --agent --status`         | `POST /tools/infra/agent-status`         |
| `telec delivery result --session-id --content`      | `POST /tools/delivery/result`            |
| `telec delivery file --session-id --path`           | `POST /sessions/{id}/file` (existing)    |
| `telec delivery widget --session-id --data`         | `POST /tools/delivery/widget`            |
| `telec delivery escalate --customer --reason`       | `POST /tools/delivery/escalate`          |
| `telec channels publish --channel --payload`        | `POST /api/channels/{name}/publish`      |
| `telec channels list [--project]`                   | `GET /api/channels/`                     |

---

## Phase 1: REST API Tool Endpoints

### Task 1.1: Create tool routes module

**File(s):** `teleclaude/api/tool_routes.py` (new)

Create a FastAPI APIRouter with the 12 new endpoints. Each endpoint:

- Extracts typed parameters from the request body
- Reads `X-Caller-Session-Id` header
- Calls the appropriate backend function
- Returns JSON result

The router needs access to `AdapterClient`, `DaemonCache`, `db`, and
`RedisTransport` — pass these via FastAPI dependency injection or app state,
same pattern as existing endpoints in `api_server.py`.

For workflow endpoints, import from `teleclaude.workflow.state_machines`.
For context, import from `teleclaude.context_selection.api`.
For channels, import from `teleclaude.channels.publisher`.

- [ ] Create `teleclaude/api/tool_routes.py` with `APIRouter(prefix="/tools")`
- [ ] Implement sessions group (2 endpoints: command, unsubscribe)
- [ ] Implement workflow group (5 endpoints)
- [ ] Implement infra group (2 endpoints: deploy, agent-status)
- [ ] Implement delivery group (3 endpoints: result, widget, escalate)
      (Channels: use existing `/api/channels/` endpoints — no new routes needed)

### Task 1.2: Mount tool router on API server

**File(s):** `teleclaude/api_server.py`

- [ ] Import `tool_router` from `teleclaude.api.tool_routes`
- [ ] Mount via `self.app.include_router(tool_router)` in `__init__`
- [ ] Pass required dependencies via app state (same pattern as existing routes)

---

## Phase 2: CLI Tool Client

### Task 2.1: Create synchronous tool client

**File(s):** `teleclaude/cli/tool_client.py` (new)

A lightweight sync HTTP client for one-shot CLI calls:

```python
import httpx
from teleclaude.constants import API_SOCKET_PATH

def tool_api_call(method: str, path: str, json: dict | None = None,
                  params: dict | None = None) -> dict:
    """Synchronous API call to daemon. Returns JSON result."""
    session_id = _read_caller_session_id()
    headers = {"x-caller-session-id": session_id} if session_id else {}
    transport = httpx.HTTPTransport(uds=API_SOCKET_PATH)
    with httpx.Client(transport=transport, base_url="http://localhost",
                      timeout=30.0) as client:
        resp = client.request(method, path, json=json, params=params,
                              headers=headers)
        resp.raise_for_status()
        return resp.json()

def _read_caller_session_id() -> str | None:
    """Read caller session ID from $TMPDIR/teleclaude_session_id."""
    ...
```

- [ ] Create `teleclaude/cli/tool_client.py`
- [ ] Implement `tool_api_call()` with sync httpx + Unix socket transport
- [ ] Implement `_read_caller_session_id()` from `$TMPDIR`
- [ ] Handle daemon unavailable (socket missing/connection refused → stderr + exit 1)
- [ ] Handle HTTP errors (4xx/5xx → stderr + exit 1)

---

## Phase 3: CLI Subcommand Groups with Rich Help

### Task 3.1: Create tool command handlers

**File(s):** `teleclaude/cli/tool_commands.py` (new)

One handler function per group. Each handler:

1. Parses subcommand and flags from args
2. Calls `tool_api_call()` with appropriate method/path/params
3. Prints JSON to stdout via `json.dumps(result, indent=2)`
4. Has rich `--help` with behavioral guidance and examples

The help text for each subcommand must:

- Carry behavioral guidance from MCP tool descriptions (timer patterns,
  reason gates, required workflows, etc.)
- Include usage examples covering every parameter and input shape
- Use structured format: Usage, Description, Arguments, Options, Examples

Source material for behavioral guidance: `teleclaude/mcp/tool_definitions.py`
contains the rich description strings that must transfer to help text.

- [ ] Implement `handle_sessions(args)` — list, start, send, tail, command, unsubscribe, end
- [ ] Implement `handle_workflow(args)` — prepare, work, maintain, mark-phase, set-deps
- [ ] Implement `handle_infra(args)` — computers, projects, deploy, agent-status
- [ ] Implement `handle_delivery(args)` — result, file, widget, escalate
- [ ] Implement `handle_channels(args)` — publish, list
- [ ] Enrich `telec docs --help` with two-phase flow guidance and examples
- [ ] Relocate `teleclaude__help` to `telec infra help` (static text)
- [ ] Each handler has rich `--help` with examples covering all parameters

### Task 3.2: Add CLI surface definitions and dispatch

**File(s):** `teleclaude/cli/telec.py`

Add new entries to `CLI_SURFACE`, `TelecCommand`, and `_handle_cli_command()`:

- [ ] Add 5 new enum values to `TelecCommand` (sessions, workflow, infra, delivery, channels)
- [ ] Add 5 new entries to `CLI_SURFACE` with subcommands and flags
- [ ] Add dispatch cases in `_handle_cli_command()` for each group
- [ ] Update `_handle_completion()` for new groups
- [ ] Update `_usage_main()` output (new groups appear in help)

### Task 3.3: Remove legacy aliases

**File(s):** `teleclaude/cli/telec.py`

- [ ] Remove `CLAUDE`, `GEMINI`, `CODEX`, `LIST` from `TelecCommand` enum
- [ ] Remove their entries from `CLI_SURFACE`
- [ ] Remove dispatch cases in `_handle_cli_command()`
- [ ] Remove `_quick_start()` and `_quick_start_via_api()` (verify not used elsewhere)
- [ ] Remove `_complete_agent()` completion handler
- [ ] Remove `_handle_list()` handler (`telec sessions list` replaces it)

---

## Phase 4: Telec-CLI Spec Doc + Validation

### Task 4.1: Update telec-cli spec doc with @exec directives

**File(s):** `docs/global/general/spec/tools/telec-cli.md`

Add `@exec` directive sections for each baseline tool:

```markdown
## CLI surface

<!-- @exec: telec -h -->

## Baseline tools

### `telec docs`

<!-- @exec: telec docs -h -->

### `telec sessions list`

<!-- @exec: telec sessions list -h -->

### `telec sessions start`

<!-- @exec: telec sessions start -h -->

### `telec sessions send`

<!-- @exec: telec sessions send -h -->

### `telec sessions command`

<!-- @exec: telec sessions command -h -->

### `telec sessions tail`

<!-- @exec: telec sessions tail -h -->

### `telec infra deploy`

<!-- @exec: telec infra deploy -h -->
```

- [ ] Update telec-cli spec doc with baseline tool `@exec` directives
- [ ] Run `telec sync` to verify expansion
- [ ] Verify expanded output in AGENTS.md includes rich help with examples

### Task 4.2: Functional tests

Test tool subcommands against a running daemon:

- [ ] Test `telec sessions list` returns valid JSON
- [ ] Test `telec sessions start` with required params
- [ ] Test `telec workflow prepare --slug test-slug`
- [ ] Test `telec infra computers` returns computer list
- [ ] Test `telec channels list` returns JSON
- [ ] Test `telec docs` returns snippet index (no IDs)
- [ ] Test `telec docs id1,id2` returns full snippet content (with IDs)
- [ ] Test `telec infra help` returns capabilities text

### Task 4.3: Help text quality verification

- [ ] Verify every subcommand `--help` includes Examples section
- [ ] Verify every parameter appears in at least one example
- [ ] Verify behavioral guidance from MCP descriptions is present
- [ ] Verify complex tools (render_widget) have multiple examples
      covering different input shapes

### Task 4.4: Regression tests

- [ ] Run `make lint`
- [ ] Run `make test`
- [ ] Verify `telec sync`, `telec init`, `telec docs`, `telec todo`, `telec config` unchanged
- [ ] Verify `telec list` is removed (replaced by `telec sessions list`)
- [ ] Verify `telec sessions list` returns session data
- [ ] Verify `telec --help` shows new subcommand groups (no legacy aliases)
- [ ] Verify TUI still works (existing REST endpoints unaffected)

---

## File Summary

| File                              | Action  | Purpose                                                  |
| --------------------------------- | ------- | -------------------------------------------------------- |
| `teleclaude/api/tool_routes.py`   | **new** | 12 REST API endpoints for tools                          |
| `teleclaude/cli/tool_client.py`   | **new** | Sync HTTP client for CLI tool calls                      |
| `teleclaude/cli/tool_commands.py` | **new** | Subcommand group handlers with rich help                 |
| `teleclaude/api_server.py`        | modify  | Mount tool router                                        |
| `teleclaude/cli/telec.py`         | modify  | New enum values, CLI_SURFACE, dispatch, enrich docs help |
| `docs/.../telec-cli.md`           | modify  | Add @exec directives for baseline tools                  |

## Scope Note

This is 3 new files + 3 modifications. The new code is mechanical (wiring
existing backend functions through REST → CLI), but there are 22 subcommands
and 12 new endpoints — total volume is significant. If a builder runs into
context pressure, the natural split point is: Phase 1-2 (API + client) as
one session, Phase 3-4 (CLI + help + validation) as a second.
