---
description: 'Comprehensive operations runbook for TeleClaude troubleshooting and observability.'
id: 'project/procedure/troubleshooting'
scope: 'project'
type: 'procedure'
---

# Ops Troubleshooting — Procedure

## Goal

Diagnose and recover TeleClaude when the stack is unstable.

## Preconditions

TeleClaude runs as a daemon managed by launchd, with multiple sockets (API, MCP), watchers, and optional Redis transport. Instability typically manifests as API timeouts, connection refused errors, or MCP unresponsiveness. Diagnosis requires correlating three log sources in order: SIGTERM watcher, API socket watcher, and daemon log.

Key artifacts:

| Artifact           | Purpose                   | Path                                                           |
| ------------------ | ------------------------- | -------------------------------------------------------------- |
| Daemon log         | Main operational log      | `/var/log/instrukt-ai/teleclaude/teleclaude.log`               |
| API unlink watcher | Socket bind/unlink events | `/var/log/instrukt-ai/teleclaude/monitoring/api-unlink.log`    |
| SIGTERM watcher    | launchctl snapshots       | `/var/log/instrukt-ai/teleclaude/monitoring/sigterm-watch.log` |
| API socket         | Local API availability    | `/tmp/teleclaude-api.sock`                                     |
| MCP socket         | MCP availability          | `/tmp/teleclaude.sock`                                         |
| Daemon PID         | Stale PID detection       | `teleclaude.pid`                                               |

Launchd services:

- System daemon (socket watcher): `/Library/LaunchDaemons/ai.instrukt.teleclaude.socketwatch.plist`
- User agent (API watcher): `~/Library/LaunchAgents/ai.instrukt.teleclaude.api-watch.plist`
- Daemon service: configured via `templates/ai.instrukt.teleclaude.daemon.plist`

## Steps

**Failure signatures**

**API timeouts in TUI:**

- Symptom: `Failed to refresh data: API request timed out`
- Likely causes: API socket unavailable or rebind in progress, daemon restart, event loop stall.

**API connection refused:**

- Symptom: `ConnectError: [Errno 61] Connection refused`
- Likely causes: `/tmp/teleclaude-api.sock` missing, daemon not running.

**Redis errors:**

- Symptom: `Too many connections`, `Connection closed by server`, SSL close-notify errors.
- Likely causes: Redis connection pool exhaustion, upstream throttling.

**MCP timeouts:**

- Symptom: MCP calls time out, `mcp-wrapper` connection refused.
- Likely causes: `/tmp/teleclaude.sock` missing, daemon restart or MCP server failure.

**Noise to ignore (not incidents):**

- Telegram edit retries due to rate limits (429 / RetryAfter).
- ElevenLabs `401 quota_exceeded`.

**Diagnostics flow**

1. **API timeout observed** — check `/tmp/teleclaude-api.sock`, check `api-unlink.log` for recent UNLINK/BIND, check `sigterm-watch.log` for daemon exits, check `teleclaude.log` for API server start/metrics.

2. **Redis transport errors** — scan `teleclaude.log` for `redis_transport` errors, check for bursts of `Too many connections`, confirm whether errors align with daemon restarts.

3. **MCP socket issues** — check `/tmp/teleclaude.sock`, scan `teleclaude.log` for MCP socket health probes.

**Correlation routine**

When incidents occur, correlate these three sources in order:

1. SIGTERM watcher (`/var/log/instrukt-ai/teleclaude/monitoring/sigterm-watch.log`)
2. API socket watcher (`/var/log/instrukt-ai/teleclaude/monitoring/api-unlink.log`)
3. Daemon log (`/var/log/instrukt-ai/teleclaude/teleclaude.log`)

The root cause usually shows up as a daemon exit + socket unlink/bind + client timeout in a short time window.

**Recovery**

Controlled restart:

```bash
make restart
make status
```

Re-bootstrap watcher services:

```bash
sudo launchctl bootout system/ai.instrukt.teleclaude.socketwatch 2>/dev/null || true
sudo launchctl bootstrap system /Library/LaunchDaemons/ai.instrukt.teleclaude.socketwatch.plist

launchctl bootout gui/$(id -u)/ai.instrukt.teleclaude.api-watch 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.instrukt.teleclaude.api-watch.plist
```

Stale PID recovery (if `make status` says NOT running but a daemon-already-running error appears):

```bash
rm -f teleclaude.pid
```

**Health checks**

Confirm watchers are running:

```bash
ps -axww -o pid,ppid,command | rg "teleclaude-unlink-watch"
ps -axww -o pid,ppid,command | rg "teleclaude-sigterm-watch"
```

Confirm watcher output is updating:

```bash
tail -n 50 /var/log/instrukt-ai/teleclaude/monitoring/api-unlink.log
tail -n 50 /var/log/instrukt-ai/teleclaude/monitoring/sigterm-watch.log
```

## Outputs

- Incident symptoms captured with correlated logs.
- Recovery attempted or escalation prepared.

## Recovery

- Restarting without checking logs first — you'll lose the evidence of what went wrong.
- Deleting `teleclaude.db` outside of worktrees — destroys session history and state.
- Ignoring watcher drift — if watcher script paths in plists don't match actual locations, monitoring silently stops.
- Assuming Redis errors are TeleClaude bugs — they're usually upstream throttling or network issues.
