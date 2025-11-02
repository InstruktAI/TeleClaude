# TeleClaude Hardening Action Plan

**Status**: System healthy, preventive improvements recommended
**Priority**: Low urgency, high value

---

## Current Status

**Polling improvements implemented** ✅:
- Timeout increased from 5s → 10s (more lenient for slow processes)
- Notification sent as NEW message (cleaner UX)
- Spec documented in CLAUDE.md

---

## Phase 1: Immediate Hardening (30 minutes)

### 1. Add ThrottleInterval to Plist Template
**File**: `config/ai.instrukt.teleclaude.daemon.plist.template`

**Change**:
```xml
<key>KeepAlive</key>
<true/>
<key>ThrottleInterval</key>
<integer>10</integer>
```

**Why**: Prevents crash loops from consuming resources. If daemon crashes repeatedly, launchd waits 10 seconds between restarts.

**Risk**: None

---

### 2. Add tmux Server Health Check
**File**: `teleclaude/daemon.py`

**Add method**:
```python
async def _check_tmux_server(self) -> bool:
    """Verify tmux server is reachable on startup."""
    try:
        sessions = await self.terminal.list_tmux_sessions()
        logger.info("tmux server operational (%d sessions)", len(sessions))
        return True
    except Exception as e:
        logger.error("tmux server unavailable: %s", e)
        # Option A: Exit with error (fail-fast)
        # Option B: Continue without tmux (degraded mode)
        return False
```

**Call from `run()`**:
```python
async def run(self) -> None:
    """Start daemon main loop."""
    # ... existing startup code ...

    # Check tmux server
    if not await self._check_tmux_server():
        logger.error("Cannot connect to tmux server, exiting")
        sys.exit(1)

    # ... continue startup ...
```

**Why**: Fail-fast if tmux is unavailable, clear error in logs

**Risk**: None (improves debugging)

---

## Phase 2: Operational Improvements (2 hours)

### 3. Startup Session Reconciliation
**Purpose**: Clean up orphaned tmux sessions on daemon restart

**File**: `teleclaude/daemon.py`

**Add method**:
```python
async def _reconcile_tmux_sessions(self) -> None:
    """Reconcile tmux sessions with database on startup."""
    logger.info("Reconciling tmux sessions with database...")

    # Get all tmux sessions
    tmux_sessions = set(await self.terminal.list_tmux_sessions())

    # Get all DB sessions
    db_sessions = await self.session_manager.get_all_sessions()
    db_tmux_names = {s.tmux_session_name for s in db_sessions if s.tmux_session_name}

    # Find orphaned tmux sessions (in tmux but not in DB)
    orphaned = tmux_sessions - db_tmux_names

    if orphaned:
        logger.warning("Found %d orphaned tmux sessions: %s", len(orphaned), orphaned)
        for session_name in orphaned:
            # Option A: Kill orphaned sessions
            await self.terminal.kill_session(session_name)
            logger.info("Killed orphaned session: %s", session_name)

            # Option B: Just log (safer if unsure)
            # logger.warning("Orphaned session (not killing): %s", session_name)
    else:
        logger.info("No orphaned tmux sessions found")
```

**Call from `run()`**:
```python
async def run(self) -> None:
    # ... after tmux health check ...
    await self._reconcile_tmux_sessions()
    # ... continue startup ...
```

**Risk**: Low (could kill wrong sessions if logic is flawed)
**Mitigation**: Start with logging-only mode, then enable killing

---

### 4. Add Explicit Resource Limits to Plist
**File**: `config/ai.instrukt.teleclaude.daemon.plist.template`

**Change**:
```xml
<key>SoftResourceLimits</key>
<dict>
    <key>NumberOfFiles</key>
    <integer>4096</integer>
    <key>NumberOfProcesses</key>
    <integer>512</integer>
</dict>
```

**Why**: Explicit limits prevent runaway resource usage

**Risk**: Low (4096 FDs is generous, daemon currently uses 61)

---

## Phase 3: Advanced (Optional, Future)

### 5. Separate Startup Error Log
```xml
<key>StandardErrorPath</key>
<string>/var/log/teleclaude_startup.log</string>
```

### 6. Graceful Shutdown Handler
```python
def _register_signal_handlers(self):
    signal.signal(signal.SIGTERM, self._handle_sigterm)
    signal.signal(signal.SIGINT, self._handle_sigint)

def _handle_sigterm(self, signum, frame):
    """Handle SIGTERM (system shutdown)."""
    logger.info("Received SIGTERM, shutting down gracefully...")
    # Optionally close all tmux sessions
    # self.shutdown_event.set()
```

### 7. Prometheus Metrics
```python
from prometheus_client import start_http_server, Counter, Gauge

messages_received = Counter('teleclaude_messages_total', 'Total messages')
active_sessions = Gauge('teleclaude_sessions_active', 'Active sessions')
```

### 8. Crash Alerting (Sentry)
```python
import sentry_sdk

sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"))
```

---

## Implementation Steps

### Step 1: Phase 1 Changes
```bash
# 1. Edit plist template
nano config/ai.instrukt.teleclaude.daemon.plist.template

# 2. Add health check to daemon.py
nano teleclaude/daemon.py

# 3. Reinstall (regenerates plist from template)
make init ARGS=-y

# 4. Restart daemon
make restart

# 5. Verify
make status
tail -f /var/log/teleclaude.log
```

### Step 2: Test ThrottleInterval
```bash
# Simulate crash loop
# Edit daemon.py: add `sys.exit(1)` at start of run()
make restart

# Watch launchd throttle restarts
tail -f /var/log/teleclaude.log

# Should see 10-second gaps between restart attempts
```

### Step 3: Test tmux Health Check
```bash
# Kill tmux server
pkill -9 tmux

# Restart daemon
make restart

# Check logs - should see "tmux server unavailable" error
tail /var/log/teleclaude.log
```

---

## Decision Matrix

| Change | Effort | Risk | Value | Recommend |
|--------|--------|------|-------|-----------|
| ThrottleInterval | 5min | None | High | ✅ Yes |
| tmux Health Check | 30min | None | High | ✅ Yes |
| Session Reconciliation | 2hr | Low | Medium | ⏸️ Phase 2 |
| Resource Limits | 10min | Low | Medium | ⏸️ Phase 2 |
| Startup Error Log | 15min | None | Low | ❌ Optional |
| Graceful Shutdown | 1hr | Low | Low | ❌ Optional |
| Prometheus | 4hr | None | Medium | ❌ Future |
| Sentry | 2hr | None | High | ❌ Future |

---

## Summary

**Immediate Action**: Implement Phase 1 (ThrottleInterval + health check)
**Estimated Time**: 30 minutes
**Expected Outcome**: Improved crash resilience, better error visibility
**Breaking Changes**: None

**Next Steps**:
1. Review this plan
2. Approve Phase 1 changes
3. Implement and test
4. Decide on Phase 2 based on operational needs
