---
id: guide/troubleshooting
type: guide
scope: project
description: Comprehensive operations runbook for TeleClaude troubleshooting and observability.
---

# Ops Troubleshooting — Guide

## Goal

Provide a single, authoritative runbook for observing, diagnosing, and recovering TeleClaude when the stack is unstable.

## Steps

### Scope

- TeleClaude daemon lifecycle and launchd management
- API socket availability and TUI/API client behavior
- MCP socket availability and wrapper connectivity
- Redis transport connectivity and peer refresh behavior
- Watcher scripts and monitoring logs

### Quick entry points

- Fast checklist: `docs/project/guide/troubleshooting.md`
- Restart procedure: use `make restart` and verify with `make status`

### System inventory (installed components)

### Launchd jobs

- System daemon (socket watcher): `/Library/LaunchDaemons/ai.instrukt.teleclaude.socketwatch.plist`
- User agent (API watcher): `~/Library/LaunchAgents/ai.instrukt.teleclaude.api-watch.plist`
- Daemon service: configured via `config/ai.instrukt.teleclaude.daemon.plist.template`

### Watcher scripts

- API unlink watcher: `~/.teleclaude/scripts/teleclaude-unlink-watch.sh`
- SIGTERM watcher: `~/.teleclaude/scripts/teleclaude-sigterm-watch.sh`

### Core runtime

- Daemon log: `/var/log/instrukt-ai/teleclaude/teleclaude.log`
- SQLite DB: `teleclaude.db` (repo root)
- PID file: `teleclaude.pid` (repo root)

### Sockets

- API socket: `/tmp/teleclaude-api.sock`
- MCP socket: `/tmp/teleclaude.sock`

### Artifact map (paths you always check)

| Artifact           | Purpose                   | Path                                                         |
| ------------------ | ------------------------- | ------------------------------------------------------------ |
| Daemon log         | Main operational log      | `/var/log/instrukt-ai/teleclaude/teleclaude.log`             |
| API unlink watcher | Socket bind/unlink events | `~/.teleclaude/logs/monitoring/teleclaude-api-unlink.log`    |
| SIGTERM watcher    | launchctl snapshots       | `~/.teleclaude/logs/monitoring/teleclaude-sigterm-watch.log` |
| API socket         | Local API availability    | `/tmp/teleclaude-api.sock`                                   |
| MCP socket         | MCP availability          | `/tmp/teleclaude.sock`                                       |
| Daemon PID         | Stale PID detection       | `teleclaude.pid`                                             |
| Redis errors       | Transport failures        | `/var/log/instrukt-ai/teleclaude/teleclaude.log`             |

### Watcher health checks

### Confirm watchers are running

```bash
ps -axww -o pid,ppid,command | rg "teleclaude-unlink-watch"
ps -axww -o pid,ppid,command | rg "teleclaude-sigterm-watch"
```

### Confirm watcher output is updating

```bash
tail -n 50 ~/.teleclaude/logs/monitoring/teleclaude-api-unlink.log
tail -n 50 ~/.teleclaude/logs/monitoring/teleclaude-sigterm-watch.log
```

### If watcher output is stale

- Re-bootstrap launchd jobs (see Recovery section).
- Verify the script paths in the plists match the actual script locations.

### Failure signatures (symptoms → likely cause)

### API timeouts in TUI

- **Symptom**: `Failed to refresh data: API request timed out`
- **Likely causes**:
  - API socket unavailable or rebind in progress
  - Daemon restart
  - Event loop stalls / overload

### API connection refused

- **Symptom**: `ConnectError: [Errno 61] Connection refused`
- **Likely causes**:
  - `/tmp/teleclaude-api.sock` missing
  - Daemon not running or restarting

### Redis errors

- **Symptom**: `Too many connections`, `Connection closed by server`, SSL close-notify errors
- **Likely causes**:
  - Redis connection pool exhaustion
  - Upstream throttling or transport instability

### MCP timeouts

- **Symptom**: MCP calls time out; `mcp-wrapper` connection refused
- **Likely causes**:
  - `/tmp/teleclaude.sock` missing
  - Daemon restart or MCP server failure

### Diagnostics flow (decision tree)

1. **API timeout observed**
   - Check `/tmp/teleclaude-api.sock`
   - Check `teleclaude-api-unlink.log` for recent UNLINK/BIND
   - Check `teleclaude-sigterm-watch.log` for daemon exits
   - Check `teleclaude.log` for API server start/metrics

2. **Redis transport errors**
   - Scan `teleclaude.log` for `redis_transport` errors
   - Check for bursts of `Too many connections`
   - Check for SSL close-notify errors
   - Confirm whether errors align with daemon restarts

3. **MCP socket issues**
   - Check `/tmp/teleclaude.sock`
   - Scan `teleclaude.log` for MCP socket health probes

### Recovery (safe ops)

### Controlled restart

```bash
make restart
make status
```

### Re-bootstrap watcher services

```bash
sudo launchctl bootout system/ai.instrukt.teleclaude.socketwatch 2>/dev/null || true
sudo launchctl bootstrap system /Library/LaunchDaemons/ai.instrukt.teleclaude.socketwatch.plist

launchctl bootout gui/$(id -u)/ai.instrukt.teleclaude.api-watch 2>/dev/null || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.instrukt.teleclaude.api-watch.plist
```

### Stale PID recovery

If `make status` says NOT running but a daemon‑already‑running error appears:

```bash
rm -f teleclaude.pid
```

### Correlation routine (root cause)

When incidents occur, always correlate these three sources in order:

1. **SIGTERM watcher**  
   `~/.teleclaude/logs/monitoring/teleclaude-sigterm-watch.log`

2. **API socket watcher**  
   `~/.teleclaude/logs/monitoring/teleclaude-api-unlink.log`

3. **Daemon log**  
   `/var/log/instrukt-ai/teleclaude/teleclaude.log`

The root cause usually shows up as a **daemon exit + socket unlink/bind + client timeout** in a short time window.

### Maintenance checklist (lifecycle)

- [ ] Watchers alive and logging
- [ ] API socket present
- [ ] MCP socket present
- [ ] No recurring Redis connection errors
- [ ] Daemon uptime stable (no rapid restart cycles)

### Guardrails

## Outputs

- Incident stabilized or degraded mode understood.
- Root cause correlated across logs and watchers.

## Recovery

- Use the Recovery steps above to restore service.

- Restart only via `make restart`
- Avoid deleting `teleclaude.db` outside worktrees
- Do not ignore watcher drift; fix paths immediately
