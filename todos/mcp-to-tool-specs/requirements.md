# Requirements: mcp-to-tool-specs

## Goal

Eliminate the MCP server entirely and replace all 24 `teleclaude__*` MCP tools with
`telec` CLI subcommands. The CLI `--help` output IS the tool documentation — no
separate tool spec docs needed. Progressive disclosure happens via `@exec` directives
in the telec-cli spec doc, which `telec sync` expands inline.

This removes ~3,400 lines of MCP infrastructure (server, wrapper, handlers,
definitions, connection management) and replaces them with CLI subcommands
backed by the existing daemon REST API.

Note: `telec docs` already exists and replaces `teleclaude__get_context` —
it calls `build_context_output()` directly with the same two-phase flow
(index without IDs, full content with IDs). No new "context" group needed.

## Context

The MCP server has been a chronic source of problems:

- Socket degradation requiring 200+ lines of watchdog/monitoring code
- Complex connection management (wrapper, reconnection, handshake caching)
- Tight coupling to daemon lifecycle (restarts break agents)
- Heavy protocol overhead for what is fundamentally "call a function, get JSON back"

The existing tool spec pattern **already works** — `memory-management-api`,
`history-search`, `agent-restart`, and `telec-cli` are all tool specs loaded via
CLAUDE.md or get_context and invoked via bash. This migration extends that proven
pattern to cover all agent-facing operations.

The `<!-- @exec: telec <cmd> -h -->` directive in doc snippets auto-generates
inline documentation at `telec sync` time. The CLI surface IS the documentation
surface. No separate doc layer.

## Scope

### In scope

- Extend `telec` CLI with subcommands for remaining tools (`telec docs` already covers get_context)
- Extend the REST API with 10 new endpoints where needed
- Write rich `--help` text for each subcommand preserving the behavioral guidance
  from MCP tool descriptions (timer patterns, reason gates, workflows)
- Include usage examples in `--help` covering every parameter and input shape
- Update telec-cli spec doc with `@exec` directives for baseline tools
- Remove MCP server, wrapper, handlers, tool definitions, and all connection management
- Update AGENTS.master.md baseline to reference telec CLI instead of MCP
- Update architecture/policy docs that reference MCP tools
- Remove `mark_agent_unavailable` (legacy alias for `mark_agent_status`)

### Out of scope

- API server migration to Next.js (separate todo, runs in parallel)
- Remote computer transport changes (Redis stays)
- Telegram/Discord adapter changes
- TUI changes (TUI uses API server, not MCP)
- `telec docs` changes (it already replaces `get_context` with the same
  two-phase flow; only `--help` enrichment is needed)

## Success Criteria

- [ ] All new tool subcommands accessible via `telec` returning JSON
- [ ] `telec docs` two-phase flow documented in `--help` (index vs get by IDs)
- [ ] Every subcommand has rich `--help` with behavioral guidance and examples
- [ ] Example coverage heuristic met: every parameter/input shape touched at least once
- [ ] Baseline tools inlined in telec-cli spec doc via `@exec` directives
- [ ] Non-baseline tools discoverable via `telec --help` index
- [ ] Role-based access control enforced daemon-side (system role + human role per command)
- [ ] Permission denied returns 403 with clear error message
- [ ] Context-selection hides tools for progressive disclosure (soft gate)
- [ ] Daemon enforcement blocks calls even if agent guesses command (hard gate)
- [ ] No MCP server process running in daemon
- [ ] No `mcp-wrapper.py` in agent session config
- [ ] Agent sessions (Claude, Gemini, Codex) can perform all existing operations
- [ ] Zero functional regression for orchestration workflows (next-work, next-prepare)
- [ ] All MCP-related code deleted (mcp_server.py, mcp/, mcp-wrapper.py)
- [ ] Architecture and policy docs updated

## CLI Help as Documentation

### Hard requirement: example coverage

Every `telec` subcommand `--help` output must include usage examples that
collectively cover every input parameter and input shape at least once.

For simple tools (flags with string/boolean values), a single example showing
all flags may suffice. For complex tools with nested JSON input (e.g.,
`render_widget`), multiple examples are required to illustrate enough of the
surface that agents won't guess wrong.

**Heuristic:** every parameter or distinct input shape must appear in at least
one example. The examples section of `--help` is not decoration — it is the
primary teaching mechanism for agents.

### Progressive disclosure via `@exec`

The telec-cli spec doc (`docs/global/general/spec/tools/telec-cli.md`) uses
`<!-- @exec: telec <cmd> -h -->` directives. When `telec sync` runs, these
expand to the full help output inline. This gives agents:

- **Level 1 (index):** `telec -h` — brief one-line descriptions of all commands
- **Level 2 (detail):** Full `--help` with parameters, behavioral guidance,
  and examples — inlined for baseline tools, available via bash for others

### Baseline tools (always inlined in detail)

| CLI Command               | Purpose                                        |
| ------------------------- | ---------------------------------------------- |
| `telec docs`              | Doc snippet retrieval (already exists)         |
| `telec sessions list`     | Session discovery (replaces `telec list`)      |
| `telec sessions start`    | Session creation with workflow guidance        |
| `telec sessions send`     | Message sending with timer pattern             |
| `telec sessions run`      | Slash command dispatch with timer pattern      |
| `telec sessions tail`     | Transcript retrieval with supervision guidance |
| `telec sessions escalate` | Customer-to-admin escalation with relay mode   |

### Non-baseline tools (discoverable via index)

- Sessions: `end`, `unsubscribe`, `result`, `file`, `widget`
- Todo: `prepare`, `work`, `maintain`, `mark-phase`, `set-deps`
- Top-level: `computers`, `projects`, `deploy`
- Agents: `status`, `availability`
- Channels: `publish`, `list`

## Breakdown

This work is split into 3 sub-todos (down from the original 6):

1. **mcp-migration-telec-commands** — Add CLI subcommands with rich `--help`,
   extend REST API, update telec-cli spec doc with `@exec` directives
2. **mcp-migration-agent-config** — Remove MCP from agent bootstrap, validate
   all workflows work via telec
3. **mcp-migration-delete-mcp** — Delete all MCP code, update remaining docs

## Role Enforcement Design

### Two orthogonal axes

**System role** (what the agent process is structurally allowed to do):

| Role           | Purpose                                                     |
| -------------- | ----------------------------------------------------------- |
| `orchestrator` | Full tool access. Manages workflow, dispatches, monitors.   |
| `worker`       | Execute assigned tasks only. No spawning, no orchestration. |

**Human role** (trust level of the human behind the session, from DB):

| Role                     | Trust                                          |
| ------------------------ | ---------------------------------------------- |
| `admin`                  | Full access                                    |
| `member`                 | No deploy, no end-session, no agent-status     |
| `contributor`/`newcomer` | Same as member + more restrictions             |
| `customer`               | Help desk only — escalate, docs, render-widget |
| `unauthorized` (none)    | Read-only                                      |

Effective permission = `system_allowed AND human_allowed`.

### Enforcement flow

1. Agent runs `telec sessions start ...`
2. `telec` reads session_id from `$TMPDIR/teleclaude_session_id`
3. `telec` queries the tmux server for the current session name:
   `tmux display-message -p '#S'` → returns the real tmux session name
   (this is unforgeable — the tmux server process controls the answer,
   the agent process cannot influence it)
4. `telec` calls daemon API with two headers:
   - `X-Caller-Session-Id: {session_id}` (from file)
   - `X-Tmux-Session: {tmux_session_name}` (from tmux server)
5. Daemon looks up the claimed session_id in DB, retrieves:
   - `system_role`, `human_role` (for permission check)
   - `tmux_session_name` (for identity verification)
6. Daemon cross-checks: does the tmux session name from the header
   match the tmux session name stored in DB for this session_id?
   - Mismatch → 403 "session identity mismatch" (hijack attempt blocked)
   - Match → proceed to permission check
7. Daemon checks permission matrix for the endpoint against both roles.
   - Allowed → execute
   - Denied → 403 with clear error message
8. No session_id → 401 "session identity required"

### Credential model: dual-factor identity

The agent's identity is verified by two independent factors:

- **session_id** (from `$TMPDIR/teleclaude_session_id`): identifies which
  session the agent claims to be. The file is writable by the agent —
  it can be forged.
- **tmux session name** (from `tmux display-message -p '#S'`): identifies
  which tmux session the process is physically running in. This is
  controlled by the tmux server process, not the agent. It cannot be forged.

The daemon created both the teleclaude session and the tmux session, and
stores the mapping in its DB. Both factors must agree for any request to
proceed.

**Attack scenario (blocked):**

An agent in tmux session `tc_aaa1` (worker/customer) discovers admin
session_id `zzz-999` and writes it to its TMPDIR file:

```
telec reads file     → session_id = "zzz-999" (forged)
telec queries tmux   → tmux_session = "tc_aaa1" (real, unforgeable)
daemon looks up zzz-999 → expects tmux_session = "tc_zzz9"
daemon compares: "tc_aaa1" ≠ "tc_zzz9" → 403 DENIED
```

The only way to bypass this is to execute code inside tmux session
`tc_zzz9` — which IS the admin session itself.

**Defense layers (summary):**

| Layer                  | What it prevents                                               | Bypassable?                               |
| ---------------------- | -------------------------------------------------------------- | ----------------------------------------- |
| Filesystem sandbox     | Discovering other session_ids in `~/.teleclaude/tmp/sessions/` | Only if agent escapes sandbox             |
| UUID entropy           | Guessing session_ids (128-bit)                                 | Computationally infeasible                |
| Tmux cross-check       | Using a discovered/forged session_id                           | No — tmux server is outside agent control |
| Daemon-side role check | Executing commands beyond role clearance                       | No — roles in DB, set at session creation |

### TMPDIR remains unchanged

The agent keeps full read/write access to its `$TMPDIR` at
`~/.teleclaude/tmp/sessions/{session_id}/`. The daemon still writes
`teleclaude_session_id` there for `telec` to read. The agent CLI
(Claude/Gemini/Codex) uses TMPDIR heavily for its own temp files.

The `teleclaude_role` file is **no longer written or read** — roles live
exclusively in the daemon DB. The file-based role marker was the MCP
wrapper's mechanism and is retired with the MCP server.

Roles live in the daemon DB, set at session creation. The agent cannot
modify its own roles — they are not stored in any file the agent can
access.

### Permission matrix

| Command                      | sys:orchestrator | sys:worker | human:admin | human:member | human:customer | human:none |
| ---------------------------- | ---------------- | ---------- | ----------- | ------------ | -------------- | ---------- |
| `telec docs`                 | yes              | yes        | yes         | yes          | yes            | yes        |
| `telec sessions list`        | yes              | no         | yes         | yes          | no             | no         |
| `telec sessions start`       | yes              | no         | yes         | yes          | no             | no         |
| `telec sessions send`        | yes              | no         | yes         | yes          | no             | no         |
| `telec sessions run`         | yes              | no         | yes         | yes          | no             | no         |
| `telec sessions tail`        | yes              | read-own   | yes         | yes          | no             | no         |
| `telec sessions end`         | yes              | no         | yes         | no           | no             | no         |
| `telec sessions unsubscribe` | yes              | no         | yes         | yes          | no             | no         |
| `telec sessions result`      | yes              | yes        | yes         | yes          | yes            | no         |
| `telec sessions file`        | yes              | yes        | yes         | yes          | yes            | no         |
| `telec sessions widget`      | yes              | yes        | yes         | yes          | yes            | no         |
| `telec sessions escalate`    | yes              | no         | yes         | yes          | yes            | no         |
| `telec todo prepare`         | yes              | no         | yes         | yes          | no             | no         |
| `telec todo work`            | yes              | no         | yes         | yes          | no             | no         |
| `telec todo maintain`        | yes              | no         | yes         | yes          | no             | no         |
| `telec todo mark-phase`      | yes              | no         | yes         | yes          | no             | no         |
| `telec todo set-deps`        | yes              | no         | yes         | yes          | no             | no         |
| `telec computers`            | yes              | no         | yes         | yes          | no             | no         |
| `telec projects`             | yes              | no         | yes         | yes          | no             | no         |
| `telec deploy`               | yes              | no         | yes         | no           | no             | no         |
| `telec agents status`        | yes              | no         | yes         | no           | no             | no         |
| `telec agents availability`  | yes              | no         | yes         | yes          | no             | no         |
| `telec channels publish`     | yes              | no         | yes         | yes          | no             | no         |
| `telec channels list`        | yes              | no         | yes         | yes          | no             | no         |

### System role derivation

| Human role     | Default system role | Can override?                 |
| -------------- | ------------------- | ----------------------------- |
| `admin`        | `orchestrator`      | Yes (workers when dispatched) |
| `member`       | `orchestrator`      | Yes (workers when dispatched) |
| `customer`     | `worker`            | No (always worker)            |
| `unauthorized` | `worker`            | No (always worker)            |

System role is set explicitly when the orchestrator dispatches a worker
(same as today — `/next-*` commands derive `ROLE_WORKER`). Customers and
unauthorized users are always locked to worker.

## Constraints

- `telec` tool subcommands must work without daemon running (graceful error: "daemon unavailable")
- `--help` must include both invocation syntax and behavioral guidance from MCP descriptions
- Backward compatibility period: MCP server can coexist during migration but
  is removed at completion
- `get_context` itself transitions from MCP tool to `telec docs` — this
  is the most sensitive migration step since it's the bootstrap mechanism

## Risks

- **get_context bootstrap already solved**: `telec docs` already exists and is
  baselined in the telec-cli spec doc. No chicken-and-egg problem — agents already
  know `telec docs` from the system prompt.
- **Agent reliability**: Bash invocations are less structured than MCP tool calls.
  Mitigation: `telec` subcommands provide structured invocation with validation
  and JSON output. Rich examples in `--help` prevent misuse.
- **Multi-agent coordination**: MCP wrapper injects `caller_session_id`.
  `telec` must replicate this from `$TMPDIR/teleclaude_session_id`.
- **Role filtering migration**: Currently MCP wrapper filters tools by role
  using file-based markers (tamperable by agents). New system uses daemon-side
  dual-factor enforcement: session_id from file + tmux session name from tmux
  server. Daemon cross-checks both against its DB before checking the permission
  matrix. Even if an agent forges the session_id file, the tmux cross-check
  catches the mismatch. Context-selection provides the soft gate (hide commands
  workers don't need). Daemon enforcement provides the hard gate (block calls
  even if the agent guesses the command). See "Credential model: dual-factor
  identity" above for the detailed attack/defense analysis.

## References

- Previous research: `todos/api-migration-research.md` (Feb 17 2026)
- Session 18e3663a: Architecture discussion (Next.js as single API)
- Session 3c3aae0d: Uvicorn elimination research
- Existing tool specs: `docs/global/general/spec/tools/`
- MCP tool surface: `docs/project/spec/mcp-tool-surface.md`
