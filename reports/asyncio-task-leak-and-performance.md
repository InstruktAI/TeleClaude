# Performance Report: asyncio Task Accumulation and Memory Pressure

**Date:** 2026-03-19
**Updated:** 2026-03-20 (diagnostic data collected)
**Observed symptom:** `Resource pressure: asyncio_tasks=6790` (threshold: 500)
**Status:** Open — step 1 (diagnostic) deployed, step 2 (naming) next

---

## 1. Executive summary

The daemon's asyncio event loop accumulates tasks far beyond healthy levels. Observed peaks:
6790 (pre-restart), 1132 after ~3h uptime. A healthy daemon should stabilize at ~50–100 tasks.
The leak rate is ~10–30 untracked tasks per minute, growing linearly with uptime.

**Key diagnostic finding (2026-03-20):** Deployed task name breakdown in pressure logs.
Result: **every leaking task is unnamed** (`Task-N` with count=1 each). No named tasks
cluster. This means:
- The pipeline fan-out (`domain_pipeline_fanout`) is **not** the primary cause — it was a
  wrong hypothesis.
- The leak comes from ~30 `asyncio.create_task()` call sites that don't pass a `name=`
  parameter.
- **We cannot identify the dominant leak source until every call site is named.**

The `TaskRegistry` tracks only 6 tasks — all well-behaved. The remaining ~1100+ tasks bypass
the registry entirely.

---

## 2. Diagnostic data

### 2.1 Growth curve (fresh daemon, 2026-03-19 21:30 restart)

| Uptime | asyncio_tasks | tracked_tasks | untracked |
|--------|---------------|---------------|-----------|
| 6s | 54 | 4 | 50 |
| 66s | 63 | 6 | 57 |
| 126s | 80 | 6 | 74 |
| 186s | 91 | 6 | 85 |
| 246s | 123 | 6 | 117 |
| 906s | 259 | 6 | 253 |
| 1086s | 302 | 6 | 296 |
| 2328s | 501 | 6 | 495 |
| 10109s | 1132 | 6 | 1126 |

Linear growth: ~0.1 tasks/second, ~6 tasks/minute on average.

### 2.2 Task name breakdown at pressure threshold

```
top: Task-89974=1, Task-168905=1, Task-212=1, Task-64599=1, Task-1944=1,
     Task-79231=1, Task-180485=1, Task-190290=1, Task-41801=1, Task-101747=1,
     Task-220438=1, Task-29141=1, Task-32981=1, Task-40082=1, Task-98528=1
```

**All generic auto-generated names.** Every task is unique (count=1). No named task appears
in the top 15. The sequential IDs (up to Task-419997 at 1132 tasks alive) indicate ~420k
tasks were created total, but most completed — only ~1100 remain alive at any moment.

### 2.3 Interpretation

The leak is **distributed across multiple unnamed call sites**. Each call site contributes a
small number of long-lived or slow-completing tasks. The total accumulates because none of
them are cleaned up on any schedule. This is death by a thousand cuts, not a single hot path.

---

## 3. Call site audit: unnamed `create_task` (the leak candidates)

Every `asyncio.create_task()` call without `name=` is invisible in the diagnostic. These are
the ~30 call sites that need naming to identify which contribute the most:

### 3.1 Infrastructure loops (daemon startup — long-lived, expected)

| File | Line | Description | Has reference? |
|---|---|---|---|
| `daemon.py` | 486 | `periodic_cleanup` | Yes (`self.cleanup_task`) |
| `daemon.py` | 491 | `poller_watch_loop` | Yes |
| `daemon.py` | 495 | `_hook_outbox_worker` | Yes |
| `daemon.py` | 502 | `mirror_worker.run` | Yes |
| `daemon.py` | 540 | `resource_monitor_loop` | Yes |
| `daemon.py` | 544 | `_wal_checkpoint_loop` | Yes |
| `daemon.py` | 549 | `todo_watcher.run` | Yes |
| `daemon.py` | 556 | `launchd_watch_loop` | Yes |
| `daemon_event_platform.py` | 347 | `event_processor.start` | Yes |
| `daemon_event_platform.py` | 583 | `webhook_delivery` | Yes |
| `daemon_event_platform.py` | 589 | `_contract_sweep_loop` | Yes |
| `api_server.py` | 509 | `_watch_loop` | Yes |
| `api_server.py` | 591 | `serve_coro` (socket) | Yes |
| `api_server.py` | 654 | `serve_coro` (TCP) | Yes |
| `api_server.py` | 772 | `_metrics_task` | Yes |
| `transport/redis_transport/_connection.py` | 130 | connection task | Yes |
| `transport/redis_transport/_connection.py` | 153 | `_poll_redis_messages` | Yes |
| `transport/redis_transport/_connection.py` | 155 | `_heartbeat_loop` | Yes |
| `transport/redis_transport/_connection.py` | 157 | `_peer_refresh_loop` | Yes |
| `adapters/telegram/lifecycle.py` | 259 | startup housekeeping | Yes |

These are **not the leak** — they're long-lived singletons with stored references. But they
should still be named for diagnostic clarity.

### 3.2 Per-event / per-session tasks (the likely leak sources)

| File | Line | Description | Has reference? | Frequency | Leak risk |
|---|---|---|---|---|---|
| `core/tmux_io.py` | 103 | DB update (session status) | **No** | Every tmux send | **HIGH** |
| `daemon_session.py` | 129 | Background task (various) | Yes (set, cap 200) | Per session event | MEDIUM |
| `core/agent_coordinator/_coordinator.py` | 88 | Background task (various) | Yes (set, no cap) | Per hook event | **HIGH** |
| `core/polling_coordinator.py` | 344 | Session poller | Yes (callback) | Per session | LOW |
| `daemon_hook_outbox.py` | 810 | Session outbox worker | Yes (dict) | Per session | LOW |
| `core/inbound_queue.py` | 126 | Session drain worker | Yes (dict) | Per session | LOW |
| `events/pipeline.py` | 91 | Domain pipeline fan-out | Yes (set) | Per event | MEDIUM |
| `core/operations/service.py` | 311,383 | Heartbeat + progress | Partial | Per operation | MEDIUM |
| `core/operations/service.py` | 319,391 | `_record_progress` | Yes (set) | Per progress update | LOW |

### 3.3 Fire-and-forget (no reference at all)

| File | Line | Description | Frequency | Leak risk |
|---|---|---|---|---|
| `core/tmux_io.py` | 103 | DB update | Every tmux send | **CRITICAL** |
| `core/command_handlers/_agent.py` | 330 | Checkpoint injection | Per restart | LOW |
| `services/maintenance_service.py` | 169 | Restore tmux session | Per startup | LOW |
| `api/sessions_actions_routes.py` | 438 | Agent restart | Per request | MEDIUM |
| `api/ws_mixin.py` | 218 | Remote cache refresh | Per WS connect | LOW |
| `deployment/handler.py` | 158 | Execute update | Per deploy | LOW |
| `transport/redis_transport/_refresh.py` | 201 | Refresh (no registry) | Per refresh | MEDIUM |

---

## 4. Action plan

### Step 1: Name every `create_task` call (NEXT — prerequisite for all other fixes)

Add `name=` parameter to every `asyncio.create_task()` call in the daemon. Use descriptive
names: `"tmux-db-update"`, `"session-bg:{label}"`, `"coordinator-bg:{label}"`, etc.

**~30 call sites. Effort: 1 hour. Zero behavioral change. Pure observability.**

After deploying, the next pressure event shows exactly which named tasks dominate.

### Step 2: Fix the dominant leak source(s) (after step 1 data)

Based on the naming data, fix the top contributor(s). Likely candidates:

- **`tmux_io.py:103`** — `await` instead of fire-and-forget (5 min)
- **`agent_coordinator`** — add cap + warning (10 min)
- **`daemon_session`** — improve drop logging (10 min)

### Step 3: Route fire-and-forget tasks through registry

For the 7 truly unreferenced call sites (section 3.3), either:
- `await` the coroutine (if in async context and result doesn't matter for latency)
- Route through `TaskRegistry.spawn()` (if lifecycle management needed)
- Store in a local set with discard callback (minimum viable tracking)

**Effort: 30 min.**

### Step 4: Verify steady state

After steps 1–3:
- Target: `asyncio_tasks < 200` under normal load
- Target: `tracked_tasks` accounts for > 80% of `asyncio_tasks`
- Monitor for 24h to confirm no regression

---

## 5. What this report does NOT cover

- **Uvicorn/FastAPI degradation** — see `todos/api-migration-research.md`. Will be addressed
  by the TypeScript migration, not by these short-term fixes.
- **Memory (RSS) growth** — RSS was 342MB before restart, 230MB after. The task leak
  contributes to RSS growth but may not be the only cause. Monitor RSS after task fixes.
- **GC pressure** — Python's GC scales with object count. Reducing live tasks from 1100 to
  <200 will reduce GC overhead, but quantifying the impact requires before/after measurement.
