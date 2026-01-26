# AGENTS.md

## Purpose

This file provides guidance to agents when working with code in this repository.

---

# Agent Service Control — Policy

## Rule

- **Allowed lifecycle commands:** `make restart`, `make status`.
- **Allowed checks:** `make status`, `instrukt-ai-logs teleclaude --since <window> --grep <str>`.
- **Allowed setup command:** `telec init` (docs sync/watchers + hooks).
- **Conditional (only when a restart is insufficient):** `make stop`, `make start`.
- **Disallowed (only for humans):** `bin/daemon-control.sh`, `bin/init.sh`, `launchctl`, `systemctl`, direct service bootout/bootstrap/unload/load.
- Never modify host-level service configuration without explicit approval.

## Rationale

- Limits accidental downtime and avoids unsafe service operations by automation.

## Scope

- Applies to all AI agents operating in this repository.

## Enforcement

- Review agent logs for prohibited commands; treat violations as incidents.

## Exceptions

- None; any exception requires explicit human approval.

---

# Daemon Availability — Policy

## Rule

- The daemon is a 24/7 service; downtime is not acceptable outside controlled restarts.
- After any change needing a restart, call `make restart` and observe success, or verify with `make status`.
- During instability, keep SIGTERM/socket monitoring enabled and retain logs under `~/.teleclaude/logs/monitoring`.
- Verify key services after restart (MCP socket, API port, adapters).

## Rationale

- Users rely on the service continuously; unplanned downtime breaks active sessions and automation.
- Explicit restart + verification is the safest minimal-downtime path.

## Scope

- Applies to all local development and production operations of the TeleClaude daemon.

## Enforcement

- Use `make restart` only after changes that require it.
- Review recent logs with `instrukt-ai-logs teleclaude --since 2m` if stability is in doubt.
- If the daemon restarts unexpectedly, capture SIGTERM/socket monitoring logs before taking action.

## Exceptions

- None.

---

# Single Database — Policy

## Rule

- The daemon uses a single SQLite file: `teleclaude.db` at the project root.
- The database path is `${WORKING_DIR}/teleclaude.db` in `config.yml`.
- The daemon must never create, copy, or duplicate the production database file.
- Extra `.db` files in the main repo are treated as bugs and removed.
- Git worktrees use isolated `teleclaude.db` files for test isolation and must not touch production state.

## Rationale

- Prevents state fragmentation and avoids split-brain behavior.

## Scope

- Applies to the running daemon in the main repository.

## Enforcement

- Verify `teleclaude.db` path is the only active database in production.
- Delete any additional `.db` files found outside worktrees.

## Exceptions

- None in production; only isolated worktrees may use separate databases.

---

# Mcp Connection Resilience — Policy

## Rule

- MCP clients connect via `bin/mcp-wrapper.py`, not directly to the daemon.
- The wrapper must provide zero-downtime behavior across restarts and reconnects.
- Wrapper must inject `caller_session_id` into tool calls for coordination.

## Rationale

- AI agents should stay connected during daemon restarts without user intervention.

## Scope

- Applies to all MCP client connections and daemon restarts.

## Enforcement

- Ensure MCP clients use the stdio wrapper.
- Verify wrapper caches handshake responses in `logs/mcp-tools-cache.json`.
- Confirm backend proxy target is `/tmp/teleclaude.sock`.

## Exceptions

- None; bypassing the wrapper breaks resilience guarantees.
