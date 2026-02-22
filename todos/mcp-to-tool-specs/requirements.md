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

- Extend `telec` CLI with subcommands for the remaining 22 tools (2 already covered by `telec docs`)
- Extend the REST API with new endpoints where needed (12 of 22 tools lack endpoints)
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

- [ ] All 22 new tool subcommands accessible via `telec` returning JSON
- [ ] `telec docs` two-phase flow documented in `--help` (index vs get by IDs)
- [ ] Every subcommand has rich `--help` with behavioral guidance and examples
- [ ] Example coverage heuristic met: every parameter/input shape touched at least once
- [ ] Baseline tools inlined in telec-cli spec doc via `@exec` directives
- [ ] Non-baseline tools discoverable via `telec --help` index
- [ ] Role-based access control preserved via context-selection filtering
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

| CLI Command            | Purpose                                        |
| ---------------------- | ---------------------------------------------- |
| `telec docs`           | Doc snippet retrieval (already exists)         |
| `telec sessions list`  | Session discovery (replaces `telec list`)      |
| `telec sessions start` | Session creation with workflow guidance        |
| `telec sessions send`  | Message sending with timer pattern             |
| `telec sessions run`   | Slash command dispatch with timer pattern      |
| `telec sessions tail`  | Transcript retrieval with supervision guidance |
| `telec infra deploy`   | Remote deployment with workflow                |

### Non-baseline tools (discoverable via index)

- Session lifecycle: `end`, `unsubscribe`
- Workflow: `prepare`, `work`, `maintain`, `mark`, `set-deps`
- Infrastructure: `computers`, `projects`, `agent-status`
- Delivery: `result`, `send-file`, `widget`, `escalate`
- Channels: `publish`, `channels`

## Breakdown

This work is split into 3 sub-todos (down from the original 6):

1. **mcp-migration-telec-commands** — Add CLI subcommands with rich `--help`,
   extend REST API, update telec-cli spec doc with `@exec` directives
2. **mcp-migration-agent-config** — Remove MCP from agent bootstrap, validate
   all workflows work via telec
3. **mcp-migration-delete-mcp** — Delete all MCP code, update remaining docs

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
- **Role filtering migration**: Currently MCP wrapper filters tools by role.
  New system uses context-selection to control which tool specs are disclosed.
  Must not regress on least-privilege for workers.

## References

- Previous research: `todos/api-migration-research.md` (Feb 17 2026)
- Session 18e3663a: Architecture discussion (Next.js as single API)
- Session 3c3aae0d: Uvicorn elimination research
- Existing tool specs: `docs/global/general/spec/tools/`
- MCP tool surface: `docs/project/spec/mcp-tool-surface.md`
