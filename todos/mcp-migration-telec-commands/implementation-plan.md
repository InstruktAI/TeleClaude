# Implementation Plan: mcp-migration-telec-commands

## Overview

Add new REST API endpoints and `telec` CLI subcommands to replace MCP tools.
Enrich `telec docs --help`. Write rich `--help` for all new subcommands with
behavioral guidance and examples. Update the telec-cli spec doc with `@exec`
directives for baseline tools. The approach:

1. New REST endpoints extending existing resource paths in `api_server.py`
   or a separate router file. Each endpoint is a thin wrapper around existing
   backend functions (same ones MCP handlers call).
2. A shared sync HTTP helper (`teleclaude/cli/tool_client.py`) for one-shot
   CLI calls to the daemon.
3. CLI subcommand handlers — extending existing `sessions` and `todo` groups,
   adding `channels` group, and new top-level commands. Each handler includes
   rich `--help` with behavioral guidance migrated from MCP tool descriptions.
4. Wire new commands into `CLI_SURFACE`, `TelecCommand` enum, and dispatch.
5. Enrich existing `telec docs --help` with two-phase flow guidance and examples.
6. Update the telec-cli spec doc with `<!-- @exec: telec <cmd> -h -->` for
   baseline tools.

**No `telec context` group.** `telec docs` already replaces `teleclaude__get_context`
with the same two-phase flow (index without IDs, full content with IDs). The naming
"docs" is correct — this is documentation snippets, not generic context.
`teleclaude__help` folds into `telec --help` output (static text, no endpoint needed).

No new business logic. All work is wiring: REST endpoint → backend function,
CLI subcommand → REST endpoint, help text → `@exec` in spec doc.

### Key Design Decisions

1. **Resource-based grouping only.** CLI groups map to REST resources: `sessions`,
   `todo`, `channels`. No artificial groups (`workflow`, `delivery`, `infra`).
2. **Sync HTTP client** — Tool CLI commands are one-shot. No async overhead needed.
   `httpx.Client` with `HTTPTransport(uds=...)` directly.
3. **JSON to stdout** — All tool subcommands output JSON. Errors go to stderr.
4. **`caller_session_id` injection** — Read from `$TMPDIR/teleclaude_session_id`,
   sent as `X-Caller-Session-Id` header on every API call.
5. **Help text as documentation** — The `--help` output carries the full behavioral
   contract from MCP tool descriptions. Examples cover every parameter and shape.
   The telec-cli spec doc inlines baseline help via `@exec` directives.

### Endpoint Design for New Endpoints

`telec docs` (get_context) needs no REST endpoint — it calls
`build_context_output()` directly.

| Resource  | Tool               | REST Endpoint                | Backend Function                            |
| --------- | ------------------ | ---------------------------- | ------------------------------------------- |
| sessions  | run-agent-command  | `POST /sessions/run`         | `create_session(auto_command=...)`          |
| sessions  | stop-notifications | `POST /sessions/unsubscribe` | `unregister_listener()`                     |
| sessions  | escalate           | `POST /sessions/escalate`    | `DiscordAdapter.create_escalation_thread()` |
| sessions  | send-result        | `POST /sessions/{id}/result` | `client.send_message()`                     |
| todo      | next-prepare       | `POST /todo/prepare`         | `next_prepare()`                            |
| todo      | next-work          | `POST /todo/work`            | `next_work()`                               |
| todo      | mark-phase         | `POST /todo/mark-phase`      | `mark_phase()`                              |
| todo      | set-dependencies   | `POST /todo/set-deps`        | `set_dependencies()`                        |
| top-level | deploy             | `POST /deploy`               | `redis_transport.send_system_command()`     |
| top-level | agent-status       | `POST /agent-status`         | `db.mark_agent_*()`                         |

Channels already have REST endpoints at `/api/channels/` (publish and list).
`computers` and `projects` already have endpoints at `/computers` and `/projects`.

**Removed from scope:**

- `render_widget` — adapter-internal, not a CLI command
- `next-maintain` — removed (was a placeholder)

New endpoints follow the same resource-based pattern as existing ones.
No artificial namespace prefixes.

### CLI Command Mapping

`telec docs` already covers `get_context`. No new CLI command needed for it.

**`telec sessions`** — session lifecycle and operations:

| Subcommand                                          | REST Endpoint                            |
| --------------------------------------------------- | ---------------------------------------- |
| `telec sessions list [--computer ...]`              | `GET /sessions` (existing)               |
| `telec sessions start --computer --project --title` | `POST /sessions` (existing)              |
| `telec sessions send --id --message`                | `POST /sessions/{id}/message` (existing) |
| `telec sessions run --computer --command`           | `POST /sessions/run`                     |
| `telec sessions tail --id [--tail ...]`             | `GET /sessions/{id}/messages` (existing) |
| `telec sessions end --id`                           | `DELETE /sessions/{id}` (existing)       |
| `telec sessions unsubscribe --id`                   | `POST /sessions/unsubscribe`             |
| `telec sessions escalate --customer --reason`       | `POST /sessions/escalate`                |
| `telec sessions result --id --content`              | `POST /sessions/{id}/result`             |
| `telec sessions file --id --path`                   | `POST /sessions/{id}/file` (existing)    |

**`telec todo`** — work item operations (extends existing `create`, `validate`, `demo`):

| Subcommand                                      | REST Endpoint           |
| ----------------------------------------------- | ----------------------- |
| `telec todo prepare [--slug ...]`               | `POST /todo/prepare`    |
| `telec todo work [--slug ...]`                  | `POST /todo/work`       |
| `telec todo mark-phase --slug --phase --status` | `POST /todo/mark-phase` |
| `telec todo set-deps --slug --after`            | `POST /todo/set-deps`   |

**`telec channels`** — pub/sub channels (existing endpoints):

| Subcommand                                   | REST Endpoint                       |
| -------------------------------------------- | ----------------------------------- |
| `telec channels list [--project]`            | `GET /api/channels/`                |
| `telec channels publish --channel --payload` | `POST /api/channels/{name}/publish` |

**Top-level** — standalone commands:

| Subcommand                            | REST Endpoint               |
| ------------------------------------- | --------------------------- |
| `telec computers`                     | `GET /computers` (existing) |
| `telec projects --computer`           | `GET /projects` (existing)  |
| `telec deploy [--computers ...]`      | `POST /deploy`              |
| `telec agent-status --agent --status` | `POST /agent-status`        |

---

## Phase 1: REST API Endpoints

### Task 1.1: Add new endpoints

Add 10 new REST endpoints. Each endpoint:

- Extracts typed parameters from the request body
- Reads `X-Caller-Session-Id` header
- Calls the appropriate backend function
- Returns JSON result

New endpoints extend existing resource paths (`/sessions/run` sits next to
`POST /sessions`). Same patterns as existing endpoints in `api_server.py`.

- [ ] Add session endpoints: `/sessions/run`, `/sessions/unsubscribe`, `/sessions/escalate`, `/sessions/{id}/result`
- [ ] Add todo endpoints: `/todo/prepare`, `/todo/work`, `/todo/mark-phase`, `/todo/set-deps`
- [ ] Add top-level: `/deploy`, `/agent-status`
      (Channels: use existing `/api/channels/` endpoints — no new routes needed)

### Task 1.2: Mount routes on API server

**File(s):** `teleclaude/api_server.py`

- [ ] Add new routes (directly or via included router)
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

## Phase 3: CLI Subcommands with Rich Help

### Task 3.1: Implement command handlers

**File(s):** `teleclaude/cli/tool_commands.py` (new), `teleclaude/cli/telec.py` (modify)

Each handler:

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

- [ ] Extend `handle_sessions(args)` — add `run`, `unsubscribe`, `escalate`, `result`, `file`
- [ ] Extend `handle_todo(args)` — add `prepare`, `work`, `mark-phase`, `set-deps`
- [ ] Implement `handle_channels(args)` — publish, list
- [ ] Implement top-level handlers: `computers`, `projects`, `deploy`, `agent-status`
- [ ] Enrich `telec docs --help` with two-phase flow guidance and examples
- [ ] Each handler has rich `--help` with examples covering all parameters

### Task 3.2: Add CLI surface definitions and dispatch

**File(s):** `teleclaude/cli/telec.py`

Add new entries to `CLI_SURFACE`, `TelecCommand`, and `_handle_cli_command()`:

- [ ] Add `SESSIONS`, `CHANNELS`, `COMPUTERS`, `PROJECTS`, `DEPLOY`, `AGENT_STATUS` enum values
- [ ] Extend `TODO` with new subcommands in `CLI_SURFACE`
- [ ] Add new entries to `CLI_SURFACE` with subcommands and flags
- [ ] Add dispatch cases in `_handle_cli_command()` for each command
- [ ] Update `_handle_completion()` for new commands
- [ ] Update `_usage_main()` output

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

### `telec sessions run`

<!-- @exec: telec sessions run -h -->

### `telec sessions tail`

<!-- @exec: telec sessions tail -h -->

### `telec sessions escalate`

<!-- @exec: telec sessions escalate -h -->

### `telec deploy`

<!-- @exec: telec deploy -h -->
```

- [ ] Update telec-cli spec doc with baseline tool `@exec` directives
- [ ] Run `telec sync` to verify expansion
- [ ] Verify expanded output in AGENTS.md includes rich help with examples

### Task 4.2: Functional tests

Test tool subcommands against a running daemon:

- [ ] Test `telec sessions list` returns valid JSON
- [ ] Test `telec sessions start` with required params
- [ ] Test `telec todo prepare --slug test-slug`
- [ ] Test `telec computers` returns computer list
- [ ] Test `telec channels list` returns JSON
- [ ] Test `telec docs` returns snippet index (no IDs)
- [ ] Test `telec docs id1,id2` returns full snippet content (with IDs)
- [ ] Test `telec deploy` triggers deployment

### Task 4.3: Help text quality verification

- [ ] Verify every subcommand `--help` includes Examples section
- [ ] Verify every parameter appears in at least one example
- [ ] Verify behavioral guidance from MCP descriptions is present

### Task 4.4: Regression tests

- [ ] Run `make lint`
- [ ] Run `make test`
- [ ] Verify `telec sync`, `telec init`, `telec docs`, `telec todo`, `telec config` unchanged
- [ ] Verify `telec list` is removed (replaced by `telec sessions list`)
- [ ] Verify `telec sessions list` returns session data
- [ ] Verify `telec --help` shows new commands (no legacy aliases)
- [ ] Verify TUI still works (existing REST endpoints unaffected)

---

## File Summary

| File                              | Action  | Purpose                                                  |
| --------------------------------- | ------- | -------------------------------------------------------- |
| `teleclaude/api/` route modules   | **new** | 10 REST endpoints across resource groups                 |
| `teleclaude/cli/tool_client.py`   | **new** | Sync HTTP client for CLI calls                           |
| `teleclaude/cli/tool_commands.py` | **new** | Subcommand handlers with rich help                       |
| `teleclaude/api_server.py`        | modify  | Mount new routes                                         |
| `teleclaude/cli/telec.py`         | modify  | New enum values, CLI_SURFACE, dispatch, enrich docs help |
| `docs/.../telec-cli.md`           | modify  | Add @exec directives for baseline tools                  |

## Scope Note

This is 3 new files + 3 modifications. The new code is mechanical (wiring
existing backend functions through REST → CLI). If a builder runs into
context pressure, the natural split point is: Phase 1-2 (API + client) as
one session, Phase 3-4 (CLI + help + validation) as a second.
