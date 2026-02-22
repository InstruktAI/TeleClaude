# Demo: mcp-migration-agent-config

## Medium

CLI / TUI — agent sessions started via TeleClaude daemon.

## What the user observes

1. **Claude session without MCP tools**: Start a Claude session. The agent
   has `telec` on PATH but no `teleclaude__*` MCP tools. Running
   `telec docs --help` works. MCP tool calls are absent from the session.

2. **Gemini session without MCP tools**: Start a Gemini session. Same
   observation — no MCP tools visible, telec commands available.

3. **Codex session without MCP tools**: Start a Codex session. Same.

4. **Orchestrator cycle via telec**: Run a prepare -> build cycle. The
   orchestrator uses `telec workflow prepare`, `telec workflow work` etc.
   instead of MCP tools. The cycle completes.

5. **Job execution without MCP**: Force-run an agent job. It completes
   without MCP tool access, using only bash/telec.

## Validation commands

```bash
# 1. Start Claude session and check for MCP tools
telec start local --project /path/to/project --title "MCP removal test"
# In the session, ask: "List all available tools containing 'teleclaude'"
# Expected: no teleclaude__* tools found

# 2. Verify telec works in session
# In the session: telec docs --help
# Expected: help text with two-phase flow

# 3. Check Gemini session
telec start local --project /path --title "Gemini MCP test" --agent gemini
# Same check: no teleclaude__* tools

# 4. Orchestrator cycle
telec workflow prepare --slug demo-test
telec workflow work --slug demo-test
# Expected: commands execute via daemon API

# 5. Job execution
scripts/cron_runner.py --force --job memory-review
# Expected: completes without MCP tools
```

## Builder notes

The builder should refine validation commands based on actual telec CLI
surface available after Phase 1 (mcp-migration-telec-commands) is complete.
The specific subcommand names may differ.
