# Session Observability Improvements

**Status:** PRD
**Created:** 2025-11-11
**Priority:** CRITICAL

## Problem Statement

Sessions are dying mysteriously without user action. On 2025-11-11 at 05:20:32, two active sessions died simultaneously (within milliseconds), causing loss of work. Current logging provides insufficient context for root cause analysis.

### Evidence
- Both sessions polling normally until 05:20:32.521
- Tmux reported "can't find session" - sessions just vanished
- No errors, warnings, or context in logs
- No system OOM kills detected
- Pattern: 2/3 sessions lost repeatedly

## Root Cause Hypotheses

Ranked by likelihood:

1. **External process killing tmux** - `pkill`, `killall`, system cleanup script
2. **Tmux server crash** - Server died, taking all sessions
3. **Resource exhaustion** - Memory/CPU limits causing silent kills
4. **Bug in polling coordinator** - Race condition causing cleanup
5. **Database corruption** - Sessions marked closed incorrectly

## Observability Improvements

### Phase 1: Immediate (Emergency Diagnostics)

**Goal:** Capture enough data to diagnose next occurrence

#### 1.1 Enhanced Session Death Logging

When `terminal_bridge.py` detects session doesn't exist:

```python
logger.error(
    "Session died unexpectedly",
    extra={
        "session_id": session_id,
        "tmux_session_name": tmux_session_name,
        "age_seconds": time.time() - session.created_at.timestamp(),
        "last_command": get_last_command_from_output(),  # NEW
        "output_size_bytes": get_output_file_size(),  # NEW
        "polling_duration_seconds": time.time() - polling_start_time,
        "poll_count": poll_iteration,
        "active_sessions_count": len(polling_coordinator.active_sessions),  # NEW
        "system_memory_mb": psutil.virtual_memory().used // 1024 // 1024,  # NEW
        "system_cpu_percent": psutil.cpu_percent(),  # NEW
    }
)
```

#### 1.2 Session Lifecycle Events Log

New file: `session_lifecycle.log` (JSON lines format)

```json
{"timestamp": "2025-11-11T05:07:04.123Z", "event": "session_created", "session_id": "46bce692", "tmux": "mozbook-session-323c987f"}
{"timestamp": "2025-11-11T05:07:06.456Z", "event": "polling_started", "session_id": "46bce692"}
{"timestamp": "2025-11-11T05:20:32.521Z", "event": "session_death_detected", "session_id": "46bce692", "reason": "tmux_not_found", "context": {...}}
{"timestamp": "2025-11-11T05:20:32.523Z", "event": "polling_ended", "session_id": "46bce692"}
```

#### 1.3 Tmux Process Monitoring

Every 30 seconds, log tmux server health:

```python
# New background task in daemon.py
async def _monitor_tmux_health():
    while True:
        try:
            # Check tmux server process
            tmux_processes = [p for p in psutil.process_iter(['pid', 'name', 'create_time', 'memory_info'])
                             if 'tmux' in p.info['name'].lower()]

            logger.info(
                "Tmux health check",
                extra={
                    "tmux_process_count": len(tmux_processes),
                    "tmux_sessions": subprocess.run(['tmux', 'list-sessions'], capture_output=True).stdout.decode().count('\n'),
                    "active_polling_sessions": len(self.polling_coordinator.active_sessions),
                }
            )
        except Exception as e:
            logger.error(f"Tmux health check failed: {e}")

        await asyncio.sleep(30)
```

#### 1.4 Session Watchdog (Heartbeat)

Detect when sessions disappear between polls:

```python
# In output_poller.py poll() loop
previous_exists = True
for iteration in range(MAX_POLLS):
    exists = await terminal_bridge.session_exists(tmux_session_name)

    if previous_exists and not exists:
        # Session disappeared!
        logger.critical(
            "Session disappeared between polls",
            extra={
                "session_id": session_id,
                "seconds_since_last_poll": 1,  # We poll every 1 second
                "iteration": iteration,
                "other_active_sessions": [s for s in coordinator.active_sessions if s != session_id],
            }
        )

    previous_exists = exists
```

### Phase 2: Medium Term (Analytics & Alerting)

#### 2.1 Metrics Export (Prometheus format)

Expose `/metrics` endpoint with:
- `teleclaude_sessions_active` - Active session count
- `teleclaude_sessions_created_total` - Cumulative created
- `teleclaude_sessions_died_total` - Cumulative unexpected deaths
- `teleclaude_session_lifetime_seconds` - Session duration histogram
- `teleclaude_tmux_processes` - Tmux process count

#### 2.2 Structured JSON Logging

Replace current logging with structured JSON:

```python
# Configure in daemon.py startup
logging_config = {
    "version": 1,
    "formatters": {
        "json": {
            "class": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(name)s %(levelname)s %(message)s"
        }
    },
    "handlers": {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "/var/log/teleclaude.json",
            "maxBytes": 50 * 1024 * 1024,  # 50MB
            "backupCount": 5,
            "formatter": "json"
        }
    }
}
```

Benefits:
- Easy parsing with `jq`
- Elasticsearch/Loki ingestion
- Precise filtering and correlation

#### 2.3 Per-Session Log Files

Optional: Write each session's lifecycle to separate file:

```
/var/log/teleclaude/sessions/
  46bce692-8e49-4a5a-b181-facf2f88093e.log
  056efc1f-f524-4021-a944-2cbb334b13ec.log
```

Makes debugging specific sessions trivial.

### Phase 3: Long Term (Advanced Monitoring)

#### 3.1 Distributed Tracing

Use OpenTelemetry to trace requests across:
- Telegram message → Daemon → Terminal → Output polling

#### 3.2 Anomaly Detection

ML-based detection of unusual patterns:
- Session death rate spikes
- Simultaneous multi-session deaths
- Resource usage anomalies

#### 3.3 Replay/Time Travel Debugging

Record all events in SQLite for replay:
- Reconstruct exact state at any point
- Replay session lifecycle
- Debug race conditions

## Implementation Priority

### Sprint 1 (NOW - 1 day)

1. Enhanced session death logging (1.1)
2. Session lifecycle events log (1.2)
3. Session watchdog heartbeat (1.4)

### Sprint 2 (This week - 2 days)

4. Tmux health monitoring (1.3)
5. Structured JSON logging (2.2)

### Sprint 3 (Next week - 3 days)

6. Metrics export (2.1)
7. Per-session log files (2.3)

## Immediate Action Items

**For next occurrence debugging:**

1. Add this to `terminal_bridge.py:session_exists()`:
   ```python
   if not exists:
       # Capture tmux server state
       tmux_ls = subprocess.run(['tmux', 'list-sessions'], capture_output=True)
       tmux_ps = subprocess.run(['ps', 'aux'], capture_output=True)
       logger.error(f"Session {name} not found. Tmux list: {tmux_ls.stdout}, Processes: {tmux_ps.stdout}")
   ```

2. Add external process monitoring:
   ```bash
   # Run in background to catch killerswhile true; do
     date >> /tmp/tmux_monitor.log
     ps aux | grep -E "(tmux|pkill|killall)" >> /tmp/tmux_monitor.log
     sleep 5
   done &
   ```

## Success Metrics

- Time to root cause: < 5 minutes after next occurrence
- False positive rate: < 1% (don't spam logs)
- Overhead: < 5% CPU, < 50MB memory

## Questions to Answer

With these improvements, we'll be able to answer:

1. What killed the sessions? (process, signal, resource limit)
2. Was it targeted (specific sessions) or systemic (all sessions)?
3. Did anything unusual happen before death? (memory spike, command, etc.)
4. Was there a pattern? (time of day, session age, output size)
5. Can we predict and prevent future occurrences?

## Rollout Plan

1. **Test locally** with intentional session kills
2. **Deploy Sprint 1** to production
3. **Monitor for 1 week** - wait for next occurrence
4. **Analyze captured data** - determine root cause
5. **Fix underlying issue**
6. **Deploy Sprint 2 & 3** for long-term monitoring

---

**Next Steps:** Review with user, prioritize, implement Sprint 1 immediately.
