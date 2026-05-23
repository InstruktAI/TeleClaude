---
id: project/spec/feature/agent_runtime/daemon-lifecycle
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
description: The long-running daemon process lifecycle — single-instance lock, staged
  startup (DB → operations → session cache warm → adapters → event platform → API
  server → projects cache warm), shutdown ordering, and the API-server restart loop
  that keeps the in-process HTTP surface alive across crashes.
---

# Daemon Lifecycle — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The agent_runtime context is hosted by a single long-running daemon process per computer. `DaemonLifecycle` owns the deterministic startup and shutdown ordering of that process, and the recovery loop that re-launches the embedded API server if it exits unexpectedly. Everything that binds per-session machinery (polling, tmux bridge, listeners, conversation links, hook ingest, mirrors) into one runtime hangs off of this lifecycle: it warms the in-memory caches that the API and the UI read from, reconciles deliveries that might have been in flight when the previous process died, and starts the background workers that maintain liveness afterwards.

## Canonical fields

### Behavioral contract

#### Single-instance lock

```
Given a daemon process is starting
When `_acquire_lock` opens the PID file in "a+" mode and attempts `fcntl.flock(LOCK_EX | LOCK_NB)`
Then a successful lock writes the current pid into the PID file and registers an atexit release
And a `BlockingIOError` raises `DaemonLockError` with the existing pid (when readable)
And `main()` exits with status 1 on `DaemonLockError`
And the lock release is idempotent — `_release_lock` closes the handle and unlinks the PID file
```

#### Staged startup ordering

```
Given a daemon has acquired the single-instance lock and obtained the running event loop
When `lifecycle.startup()` runs (guarded by an idempotent `_started` flag)
Then it executes in this strict order:
  1. `migrate_outbox_on_startup(MAIN_DB_PATH, outbox_db_path)` — outbox schema migration
  2. `db.initialize()` — main DB connection + schema check (target: <1s)
  3. `db.set_client(client)` and bring up `OperationsService` via `set_operations_service(...)` then `operations_service.start()` (target: <1s)
  4. `_warm_local_sessions_cache()` — list every local session (including headless) from DB, build `SessionSnapshot` rows, seed `DaemonCache`; emits a slow-warm warning at ≥5s with per-stage timings (target: 1–4s)
  5. Construct `APIServer` (NOT started yet) so the event platform's websocket push callback can wire into it
  6. `client.start()` — adapter startup (target: 3–12s)
  7. `_event_platform_init()` — provided by `_DaemonEventPlatformMixin._start_event_platform`; producer must be ready before any /todos/* operation can land
  8. `_complete_startup_after_adapters()` — see below
  9. `api_server.start()` and `set_on_server_exit(handle_api_server_exit)` (target: 1–3s)
  10. `_warm_local_projects_cache()` — projects-with-todos snapshot into `DaemonCache` (target: 2–5s)
And on completion sets `_started=True` and logs total elapsed
And total elapsed ≥30s (SLOW_STARTUP_WARNING_S) triggers a slow-startup warning from `daemon.start()`
```

#### Post-adapter completion tasks

```
Given adapters have started and the event platform is up
When `_complete_startup_after_adapters` runs
Then `client.reconcile_outstanding_final_outputs(config.computer.name)` replays final agent output to UI adapters that missed it
And the `DaemonCache` is wired into the Redis transport adapter when present (`redis_transport_cache.cache = self.cache`)
And `init_voice_handler()` initializes the voice handler
And `recover_voice_transcriptions(client, command_service)` resumes any transcription left in flight by a prior process: rows persisted in `pending|in_progress|interrupted` (see `database#voice-transcription-durability-and-recovery`) are resubmitted idempotently within a bounded retry cap when their audio still exists — editing the original placeholder when a notice id was persisted — or transitioned to terminal `failed` with an audio-lost notice when it does not (orphaned temp-audio sweeping is NOT done here — it is owned by the periodic cleanup loop, consistent with this spec's rule that lifecycle startup performs no orphan sweeps)
And `inbound_queue_manager.startup()` brings up the per-session inbound queue
And `reconcile_outstanding_conversation_deliveries` re-sends bounded peer bundles for any conversation link with an orphaned `pending_through_ts`
And the API server starts AFTER these tasks have completed
```

#### Cache warm honesty

```
Given the v1 warm only seeds DB snapshots into the in-memory cache
When `_warm_local_sessions_cache` runs
Then it does NOT touch tmux, does NOT match DB rows against live tmux sessions, and does NOT (re)schedule polling for live sessions
And per-session polling resumption is the responsibility of downstream paths (hook events, send_message, explicit `polling_coordinator.schedule_polling` callers)
And orphan tmux / workspace / tmpdir detection is the responsibility of the periodic cleanup loop, NOT the lifecycle startup
```

#### Post-startup background workers

```
Given lifecycle.startup() has completed
When `TeleClaudeDaemon.start()` continues
Then it spawns the following tracked background tasks (each wired to `_log_background_task_exception`):
  - `periodic-cleanup` — `MaintenanceService.periodic_cleanup` (first iteration runs immediately, then every 3600s)
  - `poller-watch` — `MaintenanceService.poller_watch_loop`
  - `hook-outbox-worker` — outbox draining (one worker per session, parallel across sessions)
  - `mirror-worker` — transcript mirroring
  - `workflow-bridge` and `identity-bridge` — Redis subscribers translating v2 envelopes into v1 cache invalidation
  - `resource-monitor`, `wal-checkpoint`, optional `launchd-watch`
And only after these are scheduled does the daemon log "TeleClaude is running"
```

#### Orphan sweeps run from the cleanup task, not from startup

```
Given the `periodic-cleanup` task started after lifecycle.startup() runs
When the first iteration executes (no initial sleep)
Then it sweeps:
  - `cleanup_orphan_tmux_sessions` — kills tmux sessions absent from DB
  - `cleanup_orphan_workspaces` — removes workspace dirs whose session is not active in DB
  - `cleanup_orphan_session_tmpdirs` — removes per-session TMPDIRs not referenced by live sessions
  - `prune_session_map` — drops in-process hook-receiver caller→session entries
  - `db.cleanup_orphan_inbound`, `db.cleanup_orphan_session_tokens`, `db.cleanup_orphan_session_listeners`
  - `db.cleanup_terminal_voice_transcriptions` — prunes succeeded/failed voice recovery rows past the runtime retention window
  - orphan voice temp audio sweep — removes old `/tmp/teleclaude_voice/voice_*` files with no recoverable DB row
  - retention sweeps for inbound, terminal_operations, webhook_outbox, hook_outbox (7-day cutoff)
And subsequent iterations sleep 3600s between sweeps
And the lifecycle's own startup does NOT perform any orphan sweep — this is intentional, the sweep is amortized into the steady-state loop
```

#### Startup retry policy

```
Given `await daemon.start()` raises an exception
When the error is retryable (`_is_retryable_startup_error`: NetworkError, ConnectError, TimeoutError, OSError, or message mentioning "name resolution" / "connection refused" / "timed out" / "temporary failure")
Then `main()` retries up to STARTUP_MAX_RETRIES=3 attempts with exponential backoff [10s, 20s, 40s]
And non-retryable errors (configuration, authentication, lock errors) exit immediately with status 1
And exhausting retries exits with status 1
And every startup attempt acquires the daemon lock idempotently; failure during start triggers `_release_lock()` before re-raise
```

#### Shutdown ordering

```
Given a SIGTERM, SIGINT, or programmatic `request_shutdown(reason)` arrives
When `signal_handler` fires
Then it calls `daemon.request_shutdown(reason)` which marks `client.mark_shutting_down()`, sets `shutdown_event`, and logs a resource snapshot
And `main()` awaits `shutdown_event.wait()` and then calls `daemon.stop()`
And `daemon.stop()` proceeds in this order:
  1. Stop sandbox manager (release socket first)
  2. Cancel `cleanup_task`, `poller_watch_task`, `hook_outbox_task`, `mirror_worker_task`
  3. Stop per-session hook-outbox workers (`_stop_session_outbox_workers`)
  4. Stop workflow bridge, identity bridge (graceful stop + awaited task)
  5. Await `webhook_delivery_task`, `channel_subscription_worker_task`, `_deployment_fanout_task`, `_ingest_scheduler_task`, `_internal_event_bus_task`, `_event_processor_task` (5s timeout each, then cancel)
  6. Cancel `resource_monitor_task`, `_wal_checkpoint_task`, `launchd_watch_task`, `_contract_sweep_task`
  7. Close signal_ai client, EventDB, tts_manager
  8. Disconnect from chiptunes worker (the worker process persists across daemon restart)
  9. `task_registry.shutdown(timeout=5.0)` — cancel any remaining tracked tasks, including voice transcription tasks while adapters are still available for in-place interruption notices
  10. `lifecycle.shutdown()` — inbound_queue shutdown → api_server.stop() → for each adapter `adapter.stop()` → `db.close()`
  11. `_release_lock()`
And every step is best-effort: a hiccup in one step is logged and the next step still runs
And because step 9 (task registry) precedes step 10 (adapter stop), a voice transcription that runs as a tracked task is cancelled while the adapters are still alive, so its cancellation handler can mark the persisted row `interrupted` and edit the user's placeholder in place before the adapter that owns that message is torn down
```

#### API server exit detection

```
Given the embedded API server task exits while the daemon is NOT shutting down
When `handle_api_server_exit(exc, started, should_exit, socket_exists)` fires from the wired callback
Then if `shutdown_event` is set, it returns immediately
And if `should_exit` is True, it logs "API server exited cleanly; skipping restart" and returns
And otherwise it logs a warning with reason="api_task_crash" (if exc) or "api_task_done", and calls `_schedule_api_restart`
And external watchdogs may also request a restart via `schedule_api_restart(reason)`
```

#### API server restart loop

```
Given `_schedule_api_restart(reason)` runs while the loop is alive
When it creates the `api-server-restart` task and `_restart_api_server` acquires `_api_restart_lock`
Then it tracks a sliding restart window: if `now - _api_restart_window_start > API_RESTART_WINDOW_S` (default 60s), the counter resets and the window restarts
And it increments `_api_restart_attempts`
And if attempts exceed API_RESTART_MAX (default 5), it logs "API server restart limit exceeded; leaving server down" and returns False
And otherwise it sleeps API_RESTART_BACKOFF_S (default 1s) and calls `api_server.restart_server()`
And on success returns True
And on failure logs the exception and returns False
And the daemon does NOT exit when restart-limit is reached — the server stays down, the daemon stays up, and an external watchdog (launchd) is expected to react
```

### Implementation pointers (v1)

- Entry point: `teleclaude/daemon.py` — `main` (`L1053`), `TeleClaudeDaemon` class (`L245`), `TeleClaudeDaemon.start` (`L637`), `TeleClaudeDaemon.stop` (`L725`), `request_shutdown` (`L866`)
  - PID lock: `_acquire_lock` (`L511`), `_release_lock` (`L567`)
  - Retry config: `STARTUP_MAX_RETRIES`, `STARTUP_RETRY_DELAYS`, `_is_retryable_startup_error` (`L213`)
  - API restart config: `API_RESTART_MAX`, `API_RESTART_WINDOW_S`, `API_RESTART_BACKOFF_S` (`L203`)
  - Background-task wiring: `start()` schedules cleanup, poller-watch, hook-outbox, mirror-worker, workflow/identity bridges, resource monitor, WAL checkpoint, launchd watch
- Lifecycle orchestration: `teleclaude/core/lifecycle.py` — `DaemonLifecycle` (`L35`)
  - `startup` (`L71`) — staged startup, idempotent on `_started`
  - `_complete_startup_after_adapters` (`L131`) — reconcile final outputs, wire cache into Redis transport, init voice handler, inbound queue startup, reconcile conversation deliveries
  - `_warm_local_sessions_cache` (`L157`) — DB-only snapshot seed; slow-warm warning at ≥5s
  - `_warm_local_projects_cache` (`L225`) — projects + todos snapshot
  - `shutdown` (`L251`) — inbound queue → api server → adapters → db.close
  - `handle_api_server_exit` (`L267`), `_schedule_api_restart` (`L294`), `schedule_api_restart` (`L305`), `_restart_api_server` (`L309`)
- Reconciliation entry points called from startup:
  - `client.reconcile_outstanding_final_outputs(...)` — `teleclaude/core/adapter_client/_output.py:383`
  - `recover_voice_transcriptions(...)` — `teleclaude/core/voice_recovery.py`
  - `reconcile_outstanding_conversation_deliveries(...)` — `teleclaude/core/conversation_delivery.py`
- Orphan sweeps (run from `MaintenanceService.periodic_cleanup`, `teleclaude/services/maintenance_service.py:53`, NOT from `lifecycle.startup()`):
  - `cleanup_orphan_tmux_sessions`, `cleanup_orphan_workspaces`, `cleanup_orphan_session_tmpdirs` in `teleclaude/core/session_cleanup.py`
  - `db.cleanup_orphan_inbound`, `db.cleanup_orphan_session_tokens`, `db.cleanup_orphan_session_listeners`
  - `db.cleanup_terminal_voice_transcriptions` and orphan `/tmp/teleclaude_voice/voice_*` file cleanup
- CLI / launch: the daemon is launched as a standalone process (typically under launchd or systemd) running `python -m teleclaude.daemon`; under uvloop when available, falling back to `asyncio.run`.

### Cross-context references

- **identity**: tokens are revalidated lazily at request time; lifecycle does not pre-validate. The startup-time token cache is empty — population happens on first auth check after API server is up.
- **config**: `config` (`teleclaude.config`) is loaded at module import time; `RuntimeSettings` is constructed once in `TeleClaudeDaemon.__init__` and persisted via debounced JSON writes thereafter. Lifecycle does not re-read effective config mid-run.
- **session_mirrors**: no direct dependency from lifecycle. The `mirror-worker` is scheduled by `daemon.start()` AFTER `lifecycle.startup()` returns; mirror extraction reacts to `session.ended` events downstream and uses `native_file_path` captured at session end.
- **workflow** and **identity (v2)**: the `_start_workflow_bridge` and `_start_identity_bridge` tasks subscribe to v2 Redis channels and translate envelopes into v1 cache invalidation; lifecycle's role is limited to ensuring the API server (and therefore the WS broadcaster) is up before these subscribers are running.
- **session_subscriptions** / **direct-conversation-links**: reconciliation of orphaned `pending_through_ts` for peer bundles runs once at startup inside `_complete_startup_after_adapters` (`reconcile_outstanding_conversation_deliveries`).

## Known caveats

- **Cache warm is DB-only.** The lifecycle does not match cached snapshots against live tmux sessions. A session row marked active in the DB with no corresponding tmux session will appear in the cache until a downstream operation (poller_watch, periodic cleanup) discovers the mismatch.
- **Orphan tmux/workspace/tmpdir sweeps are amortized into the steady-state cleanup loop**, not into startup. The first periodic_cleanup iteration runs immediately after startup completes, so the practical effect is sweep-on-boot — but it happens after `_started=True` and after the API is accepting traffic, not before.
- **API restart leaves the daemon up on exhaustion.** When restart attempts exceed `API_RESTART_MAX` inside `API_RESTART_WINDOW_S`, the daemon does NOT exit — the HTTP surface stays down and the daemon process keeps running. An external supervisor (launchd, systemd) is the expected next layer of recovery.
- **`should_exit` is the only clean-exit signal.** A uvicorn server that exited because `should_exit` was set is treated as intentional and does NOT trigger restart. Anything else (raised exception, task done without should_exit) is treated as a crash.
- **Slow startup is a warning, not a failure.** Startup elapsed time ≥`SLOW_STARTUP_WARNING_S` (30s) emits a warning from `daemon.start()`; the warm cache also emits a per-stage breakdown when warm ≥5s. Neither aborts the boot.
- **Background tasks are started outside the lifecycle.** `lifecycle.startup()` does NOT launch periodic_cleanup, poller_watch, the hook-outbox worker, the mirror worker, or the v2 bridges — those are launched by `TeleClaudeDaemon.start()` after lifecycle.startup() returns. The split is deliberate: lifecycle owns the deterministic boot prefix; the daemon owns the steady-state worker set.
- **Chiptunes worker survives daemon restart.** Disconnecting from the chiptunes manager on shutdown does NOT stop the worker process; the daemon reattaches on next boot. This is intentional — music continuity is decoupled from daemon lifecycle.
- **Shutdown is best-effort throughout.** Every shutdown step is wrapped so a single failure (e.g., an adapter `stop()` that raises) does not prevent later steps (e.g., `db.close()`) from running. The PID lock is released last regardless of upstream errors.
