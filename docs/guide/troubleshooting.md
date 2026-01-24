---
id: guide/troubleshooting
type: guide
scope: global
description: Diagnostic steps for common TeleClaude operational issues.
---

## Goal

- Diagnose and recover from common TeleClaude operational issues.

## Preconditions

- Access to the host running the daemon.

## Steps

1. Check daemon health with `make status`.
2. Inspect logs with `instrukt-ai-logs teleclaude --since 30m` and scan for `ERROR`, `mcp-server`, `telegram-adapter`.
3. Verify adapters:
   - Telegram: confirm recent adapter activity in logs and verify the configured bot is polling.
   - MCP: confirm `/tmp/teleclaude.sock` exists and `bin/mcp-wrapper.py` can connect.
   - Redis: `redis-cli ping` if transport is used.
4. If the daemon is healthy but the bot is silent, verify admin status and `TELEGRAM_USER_IDS`.
5. If command menus are duplicated, enforce a single `telegram.is_master: true`.
6. If MCP calls time out, confirm `/tmp/teleclaude.sock` is present and responding.
7. If API calls fail, verify `/tmp/teleclaude-api.sock` is present and the daemon is healthy.
8. If API disconnects are frequent, inspect monitoring logs:
   - API socket activity: `~/.teleclaude/logs/monitoring/teleclaude-api-unlink.log`
   - SIGTERM snapshots: `~/.teleclaude/logs/monitoring/teleclaude-sigterm-watch.log`
     These should capture socket bind/unlink events and recent launchctl snapshots when the daemon exits.
9. If `make status` says NOT running but a daemon‑already‑running error appears, remove the stale `teleclaude.pid`.
10. If a session is stuck, send a message with `teleclaude__send_message`. If it remains unresponsive (or MCP is unavailable), call `POST /sessions/{session_id}/agent-restart`.
11. If instability persists, isolate the last change and revert to a known good state.

## Outputs

- Root cause identified and service restored.

## Recovery

- Restart only via `make restart` and verify with `make status`.
- Do not use `make stop` during normal recovery.
- Do not delete `teleclaude.db` outside worktrees.
