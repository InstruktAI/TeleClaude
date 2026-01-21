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
   - Telegram: confirm `/help` responds in the General topic.
   - MCP: confirm `/tmp/teleclaude.sock` and test `bin/mcp-wrapper.py`.
   - Redis: `redis-cli ping` if transport is used.
4. Recover stuck sessions: try `/cancel`, then `/resize large`, then `/close-session`.
5. As a last resort for crash loops: `make stop`, delete `teleclaude.db`, then `make start`.

## Outputs

- Root cause identified and service restored.

## Recovery

- If the daemon stays unstable, isolate recent changes and revert to a known good state.
