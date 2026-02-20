# Requirements: mcp-to-tool-specs

## Goal

Eliminate the MCP server entirely and replace all 25 `teleclaude__*` MCP tools with
bash-invocable tool specs loaded via the system prompt and progressive disclosure
through `get_context`. This removes ~3,400 lines of MCP infrastructure (server,
wrapper, handlers, definitions, connection management) and replaces them with
new `telec` subcommands and markdown tool spec docs.

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

## Scope

### In scope

- Extend `telec` CLI with tool subcommands as the unified invocation surface
- Write 25 tool spec doc snippets organized in 6 taxonomy groups
- Set up progressive disclosure (baseline vs on-demand tools)
- Create daemon JSON-RPC endpoint(s) for `telec` to call
- Remove MCP server, wrapper, handlers, tool definitions, and all connection management
- Update CLAUDE.md baseline to reference new tool specs instead of MCP
- Update all architecture/policy docs that reference MCP tools
- Migrate role-based filtering to context-selection-based disclosure
- Remove `mark_agent_unavailable` (legacy alias for `mark_agent_status`)

### Out of scope

- API server migration to Next.js (separate todo, runs in parallel)
- Remote computer transport changes (Redis stays)
- Telegram/Discord adapter changes
- TUI changes (TUI uses API server, not MCP)
- get_context implementation changes (it becomes a `telec` subcommand but
  the context-selection pipeline stays)

## Success Criteria

- [ ] All 24 tools (25 minus legacy alias) have tool spec doc snippets
- [ ] `telec` subcommands can invoke every tool and return JSON
- [ ] Baseline tools load in agent system prompt without MCP
- [ ] Advanced tools are discoverable via get_context
- [ ] Role-based access control preserved via context-selection filtering
- [ ] No MCP server process running in daemon
- [ ] No `mcp-wrapper.py` in agent session config
- [ ] Agent sessions (Claude, Gemini, Codex) can perform all existing operations
- [ ] Zero functional regression for orchestration workflows (next-work, next-prepare)
- [ ] All MCP-related code deleted (mcp_server.py, mcp/, mcp-wrapper.py)
- [ ] Architecture and policy docs updated

## Tool Taxonomy

```
docs/project/spec/tools/
├── context/           # Knowledge & orientation
│   ├── get-context    # Doc snippet retrieval (baseline)
│   └── help           # TeleClaude capabilities (baseline)
├── sessions/          # Session lifecycle
│   ├── list-sessions  # List active sessions (baseline)
│   ├── start-session  # Start AI session (baseline)
│   ├── send-message   # Message a session (baseline)
│   ├── get-session-data # Retrieve transcript (baseline)
│   ├── run-agent-command # Start session with command (on-demand)
│   ├── stop-notifications # Unsubscribe events (on-demand)
│   └── end-session    # Terminate session (on-demand)
├── workflow/          # Orchestration & planning (on-demand)
│   ├── next-prepare   # Preparation state machine
│   ├── next-work      # Build state machine
│   ├── next-maintain  # Maintenance stub
│   ├── mark-phase     # Mark phase complete
│   └── set-dependencies # Set work item deps
├── infrastructure/    # Computers & deployment (on-demand)
│   ├── list-computers # Network computers
│   ├── list-projects  # Project directories
│   ├── deploy         # Deploy to remotes
│   └── mark-agent-status # Agent availability
├── delivery/          # Output & communication (on-demand)
│   ├── send-result    # Formatted output to user
│   ├── send-file      # File to user
│   ├── render-widget  # Rich widget UI
│   └── escalate       # Escalate to human admin
└── channels/          # Pub/sub messaging (on-demand)
    ├── publish        # Publish to Redis Stream
    └── channels-list  # List active channels
```

## Progressive Disclosure

**Baseline (always loaded in system prompt):**

- `context/get-context` — Foundation of knowledge retrieval
- `context/help` — Orientation
- `sessions/list-sessions` — Most common read
- `sessions/start-session` — Most common write
- `sessions/send-message` — Most common interaction
- `sessions/get-session-data` — Monitoring sessions

**On-demand (loaded via get_context when relevant):**

- `sessions/` advanced: end-session, stop-notifications, run-agent-command
- `workflow/` entire group (only for orchestrator roles)
- `infrastructure/` entire group (only for admin/ops roles)
- `delivery/` entire group (when agent needs to output to user)
- `channels/` entire group (advanced pub/sub)

## Constraints

- `telec` tool subcommands must work without daemon running (graceful error: "daemon unavailable")
- Tool specs must include both `telec` invocation and raw curl equivalent
- Backward compatibility period: MCP server can coexist during migration but
  is removed at completion
- `get_context` itself transitions from MCP tool to `telec context query` — this
  is the most sensitive migration step since it's the bootstrap mechanism

## Risks

- **get_context bootstrap chicken-and-egg**: get_context is currently an MCP tool.
  Moving it to bash means the agent must know `telec context query` from the
  system prompt before it can discover other tools. Mitigation: baseline in CLAUDE.md.
- **Agent reliability**: Bash/curl invocations are less reliable than structured
  MCP tool calls. Mitigation: `telec` subcommands provide structured invocation
  with validation and JSON output.
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
