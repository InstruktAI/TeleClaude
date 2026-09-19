---
description: "The long-running agent_runtime service process lifecycle — single-instance lock, staged startup (storage → operations → session cache warm → adapters → event platform → request surface → projects cache warm), shutdown ordering, and the request-surface restart loop that keeps the service's external surface alive across crashes."
visibility: 'public'
---

# Daemon Lifecycle — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The agent_runtime bounded context is hosted by a single long-running service process per computer. This spec covers the deterministic startup and shutdown ordering of that process, and the recovery loop that re-launches the embedded request surface if it exits unexpectedly. Everything that binds per-session machinery (output polling, host-pane orchestration, listeners, conversation links, hook ingest, mirrors) into one runtime hangs off of this lifecycle: it warms the in-memory caches that other surfaces read from, reconciles deliveries that might have been in flight when the previous process died, and starts the background workers that maintain liveness afterwards.

## Canonical fields

### Use cases

#### Single-instance lock

```
Given an agent_runtime service process is starting
When the lock acquisition runs against the configured lock file
Then a successful acquisition records the current process identity and registers a release at exit
And a contended acquisition raises a lock error naming the holder (when readable)
And the process exits abnormally on lock error
And the lock release is idempotent
```

#### Staged startup ordering

```
Given the service has acquired the single-instance lock and obtained its event loop
When startup runs (guarded by an idempotent started flag)
Then it executes in this strict order:
  1. Outbox schema migration
  2. Storage initialization (connection plus schema check, target: <1s)
  3. Operations service initialization and start (target: <1s)
  4. Local-sessions cache warm — list every local session (including headless) from durable storage, build snapshot rows, seed the service's in-memory session cache; a slow-warm warning is emitted at >=5s with per-stage timings (target: 1–4s)
  5. Construct the request-surface so the event platform's push callback can wire into it (NOT started yet)
  6. Adapter client start (target: 3–12s)
  7. Event platform init — the producer must be ready before any workflow operation can land
  8. Post-adapter completion tasks — see below
  9. Start the request surface and wire an exit-handler callback (target: 1–3s)
  10. Local-projects cache warm — projects-with-todos snapshot into the service's in-memory project cache (target: 2–5s)
And on completion the started flag is set and total elapsed is logged
And total elapsed >=30s triggers a slow-startup warning
```

#### Post-adapter completion tasks

```
Given adapters have started and the event platform is up
When the post-adapter completion stage runs
Then outstanding final-output reconciliation replays final agent output to UI adapters that missed it
And the service's in-memory cache is wired into the transport adapter when present
And the voice handler is initialized
And voice-transcription recovery resumes any transcription left in flight by a prior process: rows persisted in pending|in_progress|interrupted (see `database#voice-transcription-durability-and-recovery`) are resubmitted idempotently within a bounded retry cap when their audio still exists — editing the original placeholder when a notice identifier was persisted — or transitioned to a terminal failed state with an audio-lost notice when it does not (orphaned temp-audio sweeping is NOT done here — it is owned by the periodic cleanup loop, consistent with this spec's rule that lifecycle startup performs no orphan sweeps)
And the inbound queue manager is brought up
And conversation-delivery reconciliation re-sends bounded peer bundles for any conversation link with an orphaned pending-through cursor
And the request surface starts AFTER these tasks have completed
```

#### Cache warm honesty

```
Given the warm only seeds durable-storage snapshots into the in-memory cache
When the local-sessions cache warm runs
Then it does NOT touch the host-pane layer, does NOT match storage rows against live host panes, and does NOT (re)schedule polling for live sessions
And per-session polling resumption is the responsibility of downstream paths (hook events, send-message, explicit polling-coordinator callers)
And orphan host-pane / workspace / per-session tmpdir detection is the responsibility of the periodic cleanup loop, NOT the lifecycle startup
```

#### Post-startup background workers

```
Given startup has completed
When the service's start sequence continues
Then it spawns the following tracked background workers (each wired to a structured exception logger):
  - Periodic cleanup (first iteration runs immediately, then every hour)
  - Poller watch
  - Hook outbox worker (one worker per session, parallel across sessions)
  - Mirror worker — transcript mirroring
  - Workflow bridge and identity bridge — translators that bring v2 envelopes into v1 cache invalidation
  - Resource monitor, write-ahead-log checkpoint, optional supervisor watch
And only after these are scheduled does the service log that it is running
```

#### UC-DL2 — Turn delivery state is reconciled before adapters can emit output

```
Given the daemon starts with accepted inputs, transcript bindings, output generations, peer cursors, or Discord send intents left by an earlier process
When staged startup reaches runtime reconciliation
Then it completes schema migration and durable turn-state reconciliation before adapters, per-session pollers, and conversation delivery may emit new output
And every existing session receives an explicit pre-cutover generation before new-code delivery can write to that session
And restart reconstructs any in-memory scheduling only from durable rows
And the independently-running agent panes and native transcripts remain the authority for work that continued while the daemon was absent
```

#### Orphan sweeps run from the cleanup task, not from startup

```
Given the periodic-cleanup task started after lifecycle startup completed
When the first iteration executes (no initial sleep)
Then it sweeps:
  - Orphan host-pane sessions — terminates host panes absent from durable storage
  - Orphan workspace directories — removes workspace dirs whose session is not active in storage
  - Orphan per-session tmpdirs — removes per-session tmpdirs not referenced by live sessions
  - In-process hook-receiver caller→session entries
  - Orphan inbound rows, session tokens, session listeners
  - Voice-transcription rows in terminal states past the runtime retention window
  - Orphan voice temp audio — removes old voice files with no recoverable durable row
  - Retention sweeps for inbound, terminal operations, webhook outbox, hook outbox (7-day cutoff)
And subsequent iterations sleep an hour between sweeps
And the lifecycle's own startup does NOT perform any orphan sweep — this is intentional, the sweep is amortized into the steady-state loop
```

#### Startup retry policy

```
Given the service start raises an exception
When the error is classified as retryable (network errors, connect errors, timeouts, OS errors, or messages mentioning "name resolution" / "connection refused" / "timed out" / "temporary failure")
Then the service retries up to a bounded attempt count with exponential backoff
And non-retryable errors (configuration, authentication, lock errors) exit immediately
And exhausting retries exits abnormally
And every startup attempt acquires the single-instance lock idempotently; failure during start releases the lock before re-raise
```

#### Shutdown ordering

```
Given a shutdown signal or a programmatic shutdown request arrives
When the signal handler fires
Then it calls the service's shutdown request which marks the adapter client as shutting down, raises the shutdown event, and logs a resource snapshot
And the service awaits the shutdown event and then runs stop
And stop proceeds in this order:
  1. Stop sandbox manager (release socket first)
  2. Cancel cleanup, poller-watch, hook-outbox, mirror-worker tasks
  3. Stop per-session hook-outbox workers
  4. Stop workflow bridge and identity bridge (graceful stop + awaited task)
  5. Await webhook delivery, channel subscription worker, deployment fanout, ingest scheduler, internal event bus, event processor (5s timeout each, then cancel)
  6. Cancel resource monitor, write-ahead-log checkpoint, supervisor watch, contract sweep tasks
  7. Close auxiliary clients (signal AI, event store, TTS manager)
  8. Disconnect from chiptunes worker (the worker process persists across service restart)
  9. Task registry shutdown with timeout — cancel any remaining tracked tasks, including voice transcription tasks while adapters are still available for in-place interruption notices
  10. Lifecycle shutdown — inbound queue shutdown → request-surface stop → for each adapter, stop → storage close
  11. Release the single-instance lock
And every step is best-effort: a hiccup in one step is logged and the next step still runs
And because the task registry step precedes the adapter stop step, a voice transcription that runs as a tracked task is cancelled while the adapters are still alive, so its cancellation handler can mark the persisted row interrupted and edit the user's placeholder in place before the adapter that owns that message is torn down
```

#### Request-surface exit detection

```
Given the embedded request-surface task exits while the service is NOT shutting down
When the wired exit-handler callback fires with the relevant flags
Then if the shutdown event is set, it returns immediately
And if the should-exit flag is true, it logs "request surface exited cleanly; skipping restart" and returns
And otherwise it logs a warning identifying whether the exit was a crash or a clean task completion, and schedules a restart
And external watchdogs may also request a restart via the schedule-restart hook
```

#### Request-surface restart loop

```
Given a restart is scheduled while the loop is alive
When the restart task acquires the restart lock
Then it tracks a sliding restart window: if the time since window-start exceeds the configured window, the counter resets and the window restarts
And it increments the attempt counter
And if attempts exceed the configured maximum, it logs "restart limit exceeded; leaving surface down" and returns failure
And otherwise it sleeps the backoff and asks the request-surface to restart
And on success returns success
And on failure logs the exception and returns failure
And the service does NOT exit when the restart limit is reached — the surface stays down, the service stays up, and an external watchdog (supervisor) is expected to react
```

#### UC-CW1: Chiptunes registry paths are durable home-root control files

```
Given the chiptunes worker has a pidfile and control socket
When the paths are resolved
Then both registry paths live flat at the TeleClaude home root
And neither registry path lives under `/tmp`
And the manager and worker import the same path constants
```

#### UC-CW2: Chiptunes worker scan uses exact same-user process identity

```
Given multiple local processes mention the chiptunes worker module
When the manager scans the process table for a live worker
Then only a same-user process launched as `-m teleclaude.chiptunes.worker` counts as the worker
And processes that merely mention the module string are ignored
And processes owned by another user are ignored
```

#### UC-CW3: Reachable chiptunes worker is adopted

```
Given a chiptunes worker process is alive
And its control socket is reachable
When the manager ensures a worker is available
Then it adopts the existing worker
And it does not spawn a replacement
And it does not terminate the reachable worker
```

#### UC-CW4: Unreachable chiptunes worker is replaced once

```
Given a chiptunes worker process is alive
And its control socket is missing or unreachable
When the manager ensures a worker is available
Then it terminates the unreachable orphan
And it clears the stale registry
And it starts at most one replacement worker
```

#### UC-CW5: Reattach reconnects to reachable chiptunes worker

```
Given a chiptunes worker process survived service restart
And its control socket is reachable
When the manager reattaches during service boot
Then it reconnects to the worker
And it requests the worker state snapshot
And it keeps music continuity without spawning a duplicate
```

#### UC-CW6: Reattach terminates unreachable chiptunes orphan

```
Given a chiptunes worker process survived service restart
And its control socket is missing or unreachable
When the manager reattaches during service boot
Then it does not reconnect to the orphan
And it terminates the orphan
And it clears the stale registry
```

#### UC-CW7: Idle chiptunes worker exits after lease window

```
Given no daemon client has connected to the chiptunes worker for longer than the idle-lease window
When the worker checks its lease
Then it requests a clean stop
And its registry is released as part of shutdown
```

#### UC-CW8: Idle chiptunes worker stays alive within lease window

```
Given the chiptunes worker has recent daemon client activity within the idle-lease window
When the worker checks its lease
Then it keeps running
And daemon restart gaps inside the lease window are tolerated
```

#### UC-DL1: Projects listing tolerates a trusted directory that is not a project checkout

```
Given a configured trusted directory exists on disk and is not a TeleClaude project checkout
When the projects-with-todos listing runs
Then the listing succeeds and returns every existing trusted directory
And the non-checkout directory carries an empty todo list
And no todo store is resolved, opened, or created for the non-checkout directory
```

#### UC-DL3: Startup work added to a stage neither extends nor reorders the boot prefix

```
Given a startup stage carries work contributed by another bounded context
When startup runs
Then the documented stage order is unchanged
And the contributed work completes inside its own stage rather than deferring a later one
```

### Cross-context references

- **identity**: tokens are revalidated lazily at request time; lifecycle does not pre-validate. The startup-time token cache is empty — population happens on first auth check after the request surface is up.
- **config**: configuration is loaded at module import time; runtime settings are constructed once during service initialization and persisted via debounced writes thereafter. Lifecycle does not re-read effective configuration mid-run.
- **session_mirrors**: no direct dependency from lifecycle. The mirror worker is scheduled by the service AFTER startup returns; mirror extraction reacts to session-end events downstream and uses the native transcript file path captured at session end.
- **workflow** and **identity (v2)**: the workflow-bridge and identity-bridge tasks subscribe to v2 channels and translate envelopes into v1 cache invalidation; lifecycle's role is limited to ensuring the request surface (and therefore the push broadcaster) is up before these subscribers are running.
- **session_subscriptions** / **direct-conversation-links**: reconciliation of orphaned pending-through cursors for peer bundles runs once at startup inside the post-adapter completion stage.

## Known caveats

- **Cache warm is durable-storage-only.** The lifecycle does not match cached snapshots against live host panes. A session row marked active in storage with no corresponding host pane will appear in the cache until a downstream operation (poller watch, periodic cleanup) discovers the mismatch.
- **Orphan host-pane/workspace/tmpdir sweeps are amortized into the steady-state cleanup loop**, not into startup. The first periodic cleanup iteration runs immediately after startup completes, so the practical effect is sweep-on-boot — but it happens after the started flag is set and after the request surface is accepting traffic, not before.
- **Request-surface restart leaves the service up on exhaustion.** When restart attempts exceed the configured maximum inside the configured window, the service does NOT exit — the external surface stays down and the service process keeps running. An external supervisor is the expected next layer of recovery.
- **The should-exit flag is the only clean-exit signal.** A request-surface task that exited because should-exit was set is treated as intentional and does NOT trigger restart. Anything else (raised exception, task done without should-exit) is treated as a crash.
- **Slow startup is a warning, not a failure.** Startup elapsed time at or beyond the slow-startup threshold (30s) emits a warning; the warm cache also emits a per-stage breakdown when warm takes 5s or more. Neither aborts the boot.
- **Background workers are started outside the lifecycle.** Lifecycle startup does NOT launch periodic cleanup, poller watch, the hook-outbox worker, the mirror worker, or the v2 bridges — those are launched by the service's start sequence after lifecycle startup returns. The split is deliberate: lifecycle owns the deterministic boot prefix; the service owns the steady-state worker set.
- **Chiptunes worker survives service restart, within bounds.** Disconnecting from the chiptunes manager on shutdown does NOT stop the worker process; on next boot the service reattaches when the worker's control socket is reachable, treats an alive-but-unreachable worker as an orphan and terminates it, and a worker with no daemon client past the idle-lease window exits on its own. Music continuity is decoupled from service lifecycle, bounded by control-socket reachability and the idle lease.
- **Shutdown is best-effort throughout.** Every shutdown step is wrapped so a single failure (e.g., an adapter stop that raises) does not prevent later steps (e.g., storage close) from running. The single-instance lock is released last regardless of upstream errors.
