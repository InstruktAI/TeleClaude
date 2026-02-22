# Implementation Plan: mcp-migration-delete-mcp

## Overview

Surgical deletion of all MCP server infrastructure (~3,400 lines) and documentation
cleanup. The work splits into two atomic commits: code deletion + reference cleanup,
then documentation updates. No behavioral changes — by the time this runs, Phases 1
(telec CLI) and 2 (agent config) have already migrated all consumers off MCP.

## Commit 1: Code Deletion and Reference Cleanup

### Task 1.1: Delete MCP server files

**File(s):** `teleclaude/mcp_server.py`, `teleclaude/mcp/`, `bin/mcp-wrapper.py`,
`teleclaude/entrypoints/mcp_wrapper.py`, `teleclaude/logs/mcp-tools-cache.json`,
`.state.json` (project root, if present)

- [ ] Delete `teleclaude/mcp_server.py`
- [ ] Delete `teleclaude/mcp/` directory entirely (handlers.py, tool_definitions.py,
      role_tools.py, protocol.py, types.py, \_\_init\_\_.py)
- [ ] Delete `bin/mcp-wrapper.py`
- [ ] Delete `teleclaude/entrypoints/mcp_wrapper.py`
- [ ] Delete `teleclaude/logs/mcp-tools-cache.json`
- [ ] Delete `.state.json` from project root if it exists

### Task 1.2: Remove MCP from daemon startup and lifecycle

**File(s):** `teleclaude/daemon.py`, `teleclaude/core/lifecycle.py`

- [ ] Remove `TeleClaudeMCPServer` import and instantiation from `daemon.py`
- [ ] Remove all MCP health monitoring constants (`MCP_WATCH_INTERVAL_S`, etc.)
- [ ] Remove all MCP server state fields (`_mcp_restart_lock`, `_last_mcp_probe_at`, etc.)
- [ ] Remove `mcp_task` and `mcp_watch_task` properties
- [ ] Remove `_handle_mcp_task_done`, `_schedule_mcp_restart`, `_restart_mcp_server`
- [ ] Remove `_probe_mcp_socket`, `_check_mcp_socket_health`, `_mcp_watch_loop`
- [ ] Remove MCP server parameter from `LifecycleManager.__init__` in `lifecycle.py`
- [ ] Remove `mcp_task` / `mcp_watch_task` fields from `LifecycleManager`
- [ ] Remove MCP start/stop logic from `LifecycleManager._start_interfaces` and `_shutdown_interfaces`
- [ ] Remove MCP-related callbacks passed from daemon to lifecycle (`handle_mcp_task_done`,
      `mcp_watch_factory`, `set_last_mcp_restart_at`)

### Task 1.3: Remove MCP constants

**File(s):** `teleclaude/constants.py`

- [ ] Remove `MCP_SOCKET_PATH` constant
- [ ] Remove `# MCP roles` section (if present as standalone constant block)

### Task 1.4: Remove MCP origin and model methods

**File(s):** `teleclaude/core/origins.py`, `teleclaude/core/models.py`,
`teleclaude/core/identity.py`

- [ ] Remove `MCP = "mcp"` from `InputOrigin` enum
- [ ] Remove `from_mcp` class methods from models in `models.py`
      (verify these are only called from deleted MCP handlers)
- [ ] Remove MCP origin check in `identity.py`

### Task 1.5: Remove MCP adapter infrastructure

**File(s):** `teleclaude/adapters/telegram_adapter.py`,
`teleclaude/adapters/telegram/input_handlers.py`,
`teleclaude/adapters/base_adapter.py`

- [ ] Remove `_mcp_message_queues` dict and MCP listener section from `telegram_adapter.py`
- [ ] Remove `register_mcp_listener`, `unregister_mcp_listener` methods
- [ ] Remove MCP queue push logic from `input_handlers.py`
- [ ] Remove `poll_mcp_messages` from `base_adapter.py`

### Task 1.6: Remove MCP from services and cleanup

**File(s):** `teleclaude/services/maintenance_service.py`,
`teleclaude/services/monitoring_service.py`,
`teleclaude/core/session_cleanup.py`

- [ ] Remove `cleanup_orphan_mcp_wrappers` function from `session_cleanup.py`
- [ ] Remove its invocation from `maintenance_service.py`
- [ ] Remove `_MCP_WRAPPER_MATCH` constant from `session_cleanup.py`
- [ ] Remove `mcp_connections` metric from `monitoring_service.py`
- [ ] Remove MCP server import from `monitoring_service.py`

### Task 1.7: Clean up agent CLI MCP wrapper references

**File(s):** `teleclaude/helpers/agent_cli.py`,
`teleclaude/install/install_hooks.py`

- [ ] Remove `ensure_codex_mcp_config` function from `install_hooks.py`
      (only injects TeleClaude's MCP wrapper into Codex config)
- [ ] Remove its call site in `install_hooks.py`
- [ ] Remove `mcp_tools_arg` field from agent spec dataclass in `agent_cli.py`
- [ ] Remove `mcp_tools` parameter from `build_agent_command` and `invoke_agent_job`
- [ ] Remove `--mcp-tools` CLI argument
- [ ] Clean up agent spec dicts that reference `mcp_tools_arg`

**Resolved:** The `--allowed-mcp-server-names _none_` hardcoded in the Gemini
`flags` string is a native Gemini CLI flag that blocks all MCP servers — it stays.
The `mcp_tools_arg` field and `mcp_tools` parameter machinery is TeleClaude's
dynamic wrapper for passing that flag at runtime — that gets deleted. In short:
remove `mcp_tools_arg`, `mcp_tools`, and `--mcp-tools`; keep the hardcoded
`--allowed-mcp-server-names _none_` in the Gemini flags string.

### Task 1.8: Clean up incidental MCP references

**File(s):** `teleclaude/hooks/receiver.py`, `teleclaude/core/adapter_client.py`,
`teleclaude/core/protocols.py`, `teleclaude/core/command_handlers.py`,
`teleclaude/api_server.py`, `teleclaude/api/session_access.py`,
`teleclaude/api/transcript_converter.py`, `teleclaude/core/session_utils.py`,
`teleclaude/tagging/youtube.py`,
`teleclaude/entrypoints/youtube_sync_subscriptions.py`

- [ ] Update or remove MCP references in comments (replace with "telec CLI" where
      the comment describes the current interface)
- [ ] Remove `mcp_tools` parameter usage from youtube and session_utils callers
- [ ] Clean up `Makefile` MCP comment

### Task 1.9: Update pyproject.toml and lock

**File(s):** `pyproject.toml`, `uv.lock`

- [ ] Remove `"mcp>=1.0.0"` from dependencies
- [ ] Remove `"teleclaude.mcp_server"` and `"teleclaude.mcp.*"` from packages list
- [ ] Remove `module = "teleclaude.mcp_server"` from tool config
- [ ] Remove MCP-related lint suppression comment
- [ ] Run `uv lock` to update lockfile

### Task 1.10: Verify code commit

- [ ] Run `make lint` — passes
- [ ] Run `make test` — passes
- [ ] Grep verify: no `*mcp*` files in `teleclaude/` (excluding .venv)
- [ ] Grep verify: no MCP imports in Python files
- [ ] Grep verify: no `teleclaude.sock` references in active code
- [ ] Commit code deletion as single atomic commit

---

## Commit 2: Documentation Cleanup

### Task 2.1: Update architecture docs

**File(s):** `docs/project/design/architecture/system-overview.md`,
`docs/project/design/architecture/daemon.md`,
`docs/project/design/architecture/mcp-layer.md`

- [ ] Delete `mcp-layer.md` (or rewrite as `tool-system.md` if architecture
      needs a tool-system overview — builder decides based on content)
- [ ] Update `system-overview.md`: remove MCP from diagrams, replace with
      telec CLI references
- [ ] Update `daemon.md`: remove MCP service section, MCP socket watcher,
      MCP restart storm recovery

### Task 2.2: Update policy docs

**File(s):** `docs/project/policy/mcp-connection-management.md`,
`docs/project/policy/mcp-tool-filtering.md`

- [ ] Delete `mcp-connection-management.md` (no longer applicable)
- [ ] Delete or rewrite `mcp-tool-filtering.md` — if role-based tool
      disclosure is now handled differently, delete and reference the new mechanism

### Task 2.3: Update spec docs

**File(s):** `docs/project/spec/mcp-tool-surface.md`

- [ ] Delete or rewrite to reference telec CLI surface
      (builder decides based on whether content has been superseded)

### Task 2.4: Evaluate third-party docs

**File(s):** `docs/third-party/a2a-protocol/mcp-integration.md`

- [ ] Review whether this doc describes external MCP integration (keep) or
      TeleClaude's MCP server (delete/update)

### Task 2.5: Regenerate AGENTS.md

**File(s):** `AGENTS.master.md`, `AGENTS.md`

- [ ] Verify no MCP references remain in `AGENTS.master.md` (confirmed clean)
- [ ] Run `telec sync` to regenerate `AGENTS.md`
- [ ] Verify regenerated `AGENTS.md` has no MCP references

### Task 2.6: Verify documentation commit

- [ ] Grep verify: no "MCP server" references in architecture docs
- [ ] Grep verify: policy docs reference telec CLI instead of MCP
- [ ] Commit documentation cleanup

---

## Phase 3: Final Validation

### Task 3.1: End-to-end verification

- [ ] Daemon starts cleanly without MCP service
- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] No remaining `mcp` references in active code (excluding .venv, .git, third-party docs if retained)
