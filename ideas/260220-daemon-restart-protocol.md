---
title: Daemon Restart Protocol — formalize discipline and verification
date: 2026-02-20
priority: medium
status: open
---

## Context

Memory review identified multiple recurring references to "restart daemon" as a friction point across memories:

- Memory #25 (10d): "Always restart daemon after code changes"
- Memory #41 (3d): Port exhaustion crashed daemon (and recovery procedure unclear)
- Distributed across procedures with inconsistent naming

**Pattern:** Daemon restarts are frequent and critical, but lack a unified protocol with clear entry/exit criteria and verification steps.

## Findings

### Current State

Daemon lifecycle is controlled by:

- `make restart` (agent-safe, per AGENTS.md)
- `make status` (agent-safe verification)
- `make stop` / `make start` (conditional, per AGENTS.md)
- Unattended procedures scattered across docs

### Problem Areas

1. **Unclear triggers:** When should agents trigger a restart?
   - "After code changes" is mentioned but not formalized
   - No automated detection of changed code vs. configuration

2. **Verification gaps:** After restart, what must be checked?
   - Socket available?
   - MCP responding?
   - Database healthy?
   - Memory API available?

3. **State management:** What happens to in-flight work?
   - Session recovery procedures?
   - Job queue?
   - Scheduled tasks?

4. **Recovery automation:** How do errors during restart get handled?
   - Failed restart needs human intervention
   - No escalation criteria defined

## Scope

Create a **Daemon Restart Protocol** that includes:

### 1. Restart Triggers (Decision Tree)

```
Event: code change in daemon/
  → Is it a runtime change (Python, config)?
    → Yes: trigger restart
    → No (docs only): no restart needed

Event: code change elsewhere (TUI, agent, script)
  → Does it interact with daemon API?
    → Yes: trigger restart
    → No: no restart needed

Event: operator manual trigger
  → Check jobs/sessions in flight
    → None: safe restart
    → Active: defer or pause first
```

### 2. Pre-Restart Checklist

- [ ] No active agent sessions (or explicitly paused)
- [ ] No scheduled jobs running
- [ ] MCP connections closing gracefully
- [ ] Database can flush pending writes

### 3. Restart Sequence

```
1. make stop
   - Gracefully shutdown daemon
   - Wait for MCP clients to disconnect (2s timeout)

2. Verify stopped
   - ps aux | grep teleclaude (should be gone)
   - ls /tmp/teleclaude-api.sock (should not exist)

3. make start
   - Start daemon service
   - Wait for socket creation (5s timeout)

4. make status
   - Verify running
   - Check resource usage
```

### 4. Post-Restart Verification (Mandatory)

- [ ] Socket available: `curl --unix-socket /tmp/teleclaude-api.sock http://localhost/health`
- [ ] MCP responding: Simple API call succeeds
- [ ] Memory API working: `curl ... /api/memory/search`
- [ ] Database healthy: Check recent logs for errors
- [ ] No resource leaks: CPU/memory stable within 10s

### 5. Failure Handling

**If restart fails:**

1. Check daemon logs: `instrukt-ai-logs teleclaude --since 5m --grep error`
2. Check service state: `make status`, `launchctl list | grep teleclaude`
3. Common issues:
   - Socket still locked (wait 5s, retry)
   - Port in use (check `lsof -i :PORT`)
   - Database corrupted (check logs, may need manual recovery)

**If rollback needed:**

- Previous daemon version unknown (not currently tracked)
- Manual restart with known-good version required

## Related

- Memory #25: Always restart daemon after code changes
- Memory #41: Port exhaustion (recovery procedure needed)
- AGENTS.md: Agent service control policy
- docs/project/procedure/service-management.md
- docs/project/procedure/restart-daemon.md (exists, may need update)
