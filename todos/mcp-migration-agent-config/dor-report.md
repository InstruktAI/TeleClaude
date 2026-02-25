# DOR Report: mcp-migration-agent-config

## Gate Verdict: PASS (score 8)

All 8 gates satisfied. Ready for implementation.

### Gate 1: Intent & Success

**Pass.** Goal is explicit: remove MCP config from agent sessions so they use
telec CLI instead. Success criteria are concrete and testable (per-agent-type
checks, orchestrator cycle, job execution).

### Gate 2: Scope & Size

**Pass.** The work is atomic — modifying 4 files (constants.py, agent_cli.py,
install_hooks.py, setup_mcp_config.sh) plus test updates. Fits a single session.
No cross-cutting changes beyond the agent configuration boundary.

### Gate 3: Verification

**Pass.** Verification path is clear: unit tests for config changes, plus
end-to-end validation of each agent type. Two edge cases handled:

- Codex CLI has no MCP-blocking flag — config removal (Task 2.2) is the
  documented fallback. Builder verifies during build.
- Worker isolation was enforced by MCP role filtering — requirements scope this
  as "verify telec equivalent or explicitly defer."

### Gate 4: Approach Known

**Pass.** All patterns already proven in the codebase:

- Claude: `--strict-mcp-config` + `"enabledMcpjsonServers": []` (used in
  `_ONESHOT_SPEC` at agent_cli.py:86-89)
- Gemini: `--allowed-mcp-server-names _none_` (used in `_ONESHOT_SPEC` at
  agent_cli.py:102)
- Codex: no CLI flag exists (`mcp_tools_arg: ""`); config removal is the gate
- Interactive profiles in `AGENT_PROTOCOL` (constants.py:306-361) need the
  same flags added — straightforward

### Gate 5: Research

**Pass (auto-satisfied).** No new third-party dependencies. All CLI flags
already exist in the codebase.

### Gate 6: Dependencies & Preconditions

**Pass.** Depends on `mcp-migration-telec-commands` (Phase 1), which is
`in_progress` with DOR score 8. Dependency declared in `roadmap.yaml`.

### Gate 7: Integration Safety

**Pass.** Changes are incremental and contained to agent configuration. MCP
server daemon continues running for non-agent consumers. Rollback is
straightforward: revert the profile flag changes.

### Gate 8: Tooling Impact

**Pass (auto-satisfied).** No tooling or scaffolding changes.

## Resolved Blockers

1. **Codex MCP blocking flag** (was blocker) — Resolved. The plan already
   documents config removal as the fallback when no CLI flag exists. This is
   a known approach, not an unknown. Builder verifies and documents findings.

2. **Worker isolation** (was blocker) — Resolved. Requirements and plan both
   scope this as "verify telec equivalent or explicitly defer." The builder
   investigates during e2e validation and either implements or creates a
   follow-up todo. Clear enough for readiness.

## Assumptions

- Phase 1 (mcp-migration-telec-commands) will be complete before this work starts.
- The MCP daemon process continues running (for non-agent consumers like
  Telegram, Discord, web).
- Existing user-level MCP configs (in home dirs) from prior installations are
  acceptable to leave in place — they are overridden by the per-session flags.
