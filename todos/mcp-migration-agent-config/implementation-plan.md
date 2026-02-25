# Implementation Plan: mcp-migration-agent-config

## Overview

Remove MCP server configuration from all agent session types so agents use
`telec` CLI subcommands instead of MCP tools. The approach modifies the agent
command profiles (AGENT_PROTOCOL), job specs, and installer scripts — all
centralized configuration points. No agent runtime code changes are needed.

This is Phase 2 of the MCP migration. Phase 1 (mcp-migration-telec-commands)
provides the `telec` CLI replacements. Phase 3 deletes the MCP server code.

## Phase 1: Disable MCP in Interactive Agent Sessions

### Task 1.1: Add MCP-disabling flags to AGENT_PROTOCOL

**File(s):** `teleclaude/constants.py`

The `AGENT_PROTOCOL` dict defines the base command profiles for each agent.
Modify the `profiles.default` and `profiles.restricted` strings to include
MCP-disabling flags.

- [ ] Claude profiles: Add `--strict-mcp-config` flag and extend the
      `--settings` JSON to include `"enabledMcpjsonServers": []`. This tells
      Claude Code to use only the settings-provided MCP list (empty) and ignore
      global config. Both `default` and `restricted` profiles need this.
- [ ] Gemini profiles: Append `--allowed-mcp-server-names _none_` to both
      `default` and `restricted` profiles. This blocks all MCP servers.
- [ ] Codex profiles: Verify Codex CLI MCP blocking. Check if
      `--allowed-mcp-server-names` or an equivalent exists. If not, the Codex
      TOML config removal (Task 2.2) is the only gate. Document findings.

### Task 1.2: Disable MCP in agent_cli.py job specs

**File(s):** `teleclaude/helpers/agent_cli.py`

The `_JOB_SPEC` dict defines commands for agent jobs (cron runner). Currently
Claude jobs inherit global MCP config. Gemini/Codex jobs similarly.

- [ ] Claude `_JOB_SPEC`: Add `--strict-mcp-config` and extend `--settings`
      JSON with `"enabledMcpjsonServers": []` to match the interactive profile.
- [ ] Gemini `_JOB_SPEC`: Add `--allowed-mcp-server-names _none_` to flags.
- [ ] Codex `_JOB_SPEC`: Apply equivalent MCP blocking if CLI supports it.
- [ ] Verify `_ONESHOT_SPEC` already blocks MCP (Claude: `enabledMcpjsonServers: []`,
      Gemini: `--allowed-mcp-server-names _none_`, Codex: no MCP tools arg). No changes
      expected here — confirm only.

---

## Phase 2: Remove MCP Config from Installer Scripts

### Task 2.1: Remove MCP config injection from setup_mcp_config.sh

**File(s):** `bin/init/setup_mcp_config.sh`

This script injects `mcpServers.teleclaude` into agent config files during
`bin/init.sh`. After this phase, new installations should not configure MCP.

- [ ] Comment out or remove the Claude MCP config block (writes to `~/.claude.json`)
- [ ] Comment out or remove the Gemini MCP config block (writes to `~/.gemini/settings.json`)
- [ ] Comment out or remove the Codex MCP config block (writes to `~/.codex/config.toml`)
- [ ] Keep the function signature intact (called by init.sh) — make it a no-op
      with a log message indicating MCP config is no longer injected.

### Task 2.2: Remove MCP config from install_hooks.py

**File(s):** `teleclaude/install/install_hooks.py`

The `configure_codex()` function calls `ensure_codex_mcp_config()` which writes
`[mcp_servers.teleclaude]` to Codex TOML config.

- [ ] Remove the call to `ensure_codex_mcp_config()` from `configure_codex()`
      (or the code path that invokes it).
- [ ] Keep the `ensure_codex_mcp_config()` function definition for now (Phase 3
      deletes it). Mark it as unused with a comment referencing the deletion phase.

---

## Phase 3: Verification

### Task 3.1: Update tests

**File(s):** `tests/unit/test_install_hooks.py`, `tests/unit/test_agent_cli.py`

- [ ] Update test_install_hooks.py tests that assert MCP config is present
      in Codex config — they should now assert it is absent.
- [ ] Add test cases verifying that AGENT_PROTOCOL profiles contain MCP-disabling
      flags (or update existing tests if they validate profile strings).
- [ ] Run `make test` — all tests pass.

### Task 3.2: Run lint

- [ ] Run `make lint` — no new violations.

### Task 3.3: End-to-end validation

Manual or semi-automated validation of agent sessions.

- [ ] Start a Claude session via TeleClaude and verify no MCP tools
      (teleclaude\_\_\*) appear in the tool list. Verify `telec` commands work
      from within the session (e.g., `telec docs --help`).
- [ ] Start a Gemini session and verify no MCP tools appear.
- [ ] Start a Codex session and verify no MCP tools appear.
- [ ] Run a full orchestrator cycle (prepare -> build -> review -> finalize)
      and confirm it completes using telec tools.
- [ ] Verify worker isolation: worker sessions should not have orchestration
      commands available (this was enforced by MCP role filtering — confirm
      telec equivalent or note if deferred).
- [ ] Verify agent jobs still function: run `cron_runner.py --force --job`
      for one job and confirm it completes.
- [ ] Verify `$TMPDIR/teleclaude_session_id` is still written (tmux_bridge.py
      handles this — should be unaffected, but confirm).
- [ ] Verify multi-computer session management is unaffected (telec commands
      talk to daemon API, same as before).

---

## Phase 4: Review Readiness

- [ ] Confirm all implementation tasks are marked `[x]`
- [ ] Confirm requirements are reflected in code changes
- [ ] Document any deferrals explicitly in `deferrals.md` if applicable
- [ ] Commit changes
