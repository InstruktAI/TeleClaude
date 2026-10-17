---
description: "The long-running agent_runtime service process lifecycle — single-instance lock, staged startup (storage → operations → session cache warm → adapters → event platform → request surface → projects cache warm), shutdown ordering, and the request-surface restart loop that keeps the service's external surface alive across crashes."
visibility: 'public'
---

# Daemon Lifecycle — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

The agent_runtime bounded context is hosted by a single long-running service process per computer. This spec covers the deterministic startup and shutdown ordering of that process, and the recovery loop that re-launches the embedded request surface if it exits unexpectedly. Everything that binds per-session machinery (output polling, host-pane orchestration, listeners, conversation links, hook ingest, mirrors) into one runtime hangs off of this lifecycle: it warms the in-memory caches that other surfaces read from, reconciles deliveries that might have been in flight when the previous process died, and starts the background workers that maintain liveness afterwards.

## Canonical fields

### Startup and recovery invariants

A per-computer lock admits one service process. A start attempt that fails
releases its lock; a competing process exits without opening the runtime.
Session-cache warm-up seeds durable rows only: it does not probe host panes or
schedule per-session polling. Hooks, messages, and the polling coordinator
resume polling, while periodic cleanup owns orphan discovery.

Transient network, connection, timeout, and operating-system failures retry
startup with bounded backoff; configuration, authentication, and lock failures
exit immediately. An unexpected request-surface exit is retried only outside
shutdown; exhausted recovery requests ordinary service shutdown so the service
manager can relaunch it.

### Use cases

#### Staged startup ordering

Storage migration and initialization precede operations startup and local source
materialization. Adapters receive the local session state their startup
requires. Domain-event publication is ready before producers can emit, and
each required consumer's progress is established before the source activity it
must observe. Registering or scheduling a reader alone does not establish that
handover.
The producer and reader positions for both event source streams are prepared
independently of adapter startup. Handler execution remains gated on its own
dependencies, including request-surface binding where required.

The request surface is constructed before its event callbacks are wired, and
its listener is bound before consumers that call it execute. Source seeding and
live session materialization share an explicit coverage handover before the
runtime declares startup complete. The handover reconciles current source
state through the cache owner under
`local/projects/teleclaude/design/architecture/cache`; it does not publish
previously captured startup rows after newer live materialization.

Post-adapter reconciliation, request-surface recovery and project warmup retain
their owner contracts. Startup remains idempotent and reports completion and
slow stages through the lifecycle's configured observations. These readiness
boundaries follow `sdlc/principle/architectural-defaults` and
`sdlc/policy/domain-ownership`.

#### UC-DL6: Post-adapter completion tasks

```
Given adapters have started and the event platform is up
When the post-adapter completion stage runs
Then the service's in-memory cache is wired into the transport adapter when present
And the voice handler is initialized
And voice-transcription recovery resumes any transcription left in flight by a prior process: rows persisted in pending|in_progress|interrupted (see `database#voice-transcription-durability-and-recovery`) are resubmitted idempotently within a bounded retry cap when their audio still exists — editing the original placeholder when a notice identifier was persisted — or transitioned to a terminal failed state with an audio-lost notice when it does not (orphaned temp-audio sweeping is NOT done here — it is owned by the periodic cleanup loop, consistent with this spec's rule that lifecycle startup performs no orphan sweeps)
And operations normalized to their stale outcome by the operations stage have their outcomes delivered here (see `durable-operation-outcomes#uc-do3-staleness-is-an-outcome-and-reaches-the-caller` for the delivery contract)
And session startups a prior process left unfinished are taken up as UC-DL9 states
And the inbound queue manager is brought up
And conversation-delivery reconciliation re-sends bounded peer bundles for any conversation link with an orphaned pending-through cursor
And outstanding final-output reconciliation is NOT done here — it is scheduled as a background pass after the request surface starts
And the request surface starts AFTER these tasks have completed
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
  - Orphan inbound rows, session listeners
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

#### An operator can stop the daemon without losing accepted work

```gherkin
Given a human operator needs to stop or restart the daemon while acknowledged work is active
When ordinary shutdown begins
Then new work is refused and acknowledged work settles or reaches a durable recovery boundary before its required dependencies stop
And independently running agent turns continue without being terminated
```

#### UC-DL4: Shutdown without active playback avoids invalid cancellation

```gherkin
Given the service has no active playback generation to cancel
When a human operator stops the service
Then shutdown completes without reporting a playback-cancellation validation failure
```

#### Request-surface exit detection

```
Given the embedded request-surface task, or the webhook ingress listener it starts, exits while the service is NOT shutting down
When the wired exit-handler callback fires with the relevant flags
Then if the shutdown event is set, it returns immediately
And if the should-exit flag is true, it logs "request surface exited cleanly; skipping restart" and returns
And otherwise it logs a warning identifying which surface exited and whether the exit was a crash or a clean task completion, and schedules a restart
And external watchdogs may also request a restart via the schedule-restart hook
```

#### Request-surface restart loop

```
Given a restart is scheduled while the loop is alive
When the restart task acquires the restart lock
Then it tracks a sliding restart window: if the time since window-start exceeds the configured window, the counter resets and the window restarts
And it increments the attempt counter
And if attempts exceed the configured maximum, it logs that the restart limit is exhausted and requests the service's ordinary shutdown, which the service manager follows with a relaunch
And otherwise it sleeps the backoff and asks the request-surface to restart
And on success returns success
And on failure logs the exception and schedules another restart, counted in the same window
And the service never stays up with its request surface left down
```

#### UC-CW1: Chiptunes registry paths are durable home-root control files

#### UC-CW2: Chiptunes worker scan uses exact same-user process identity

#### UC-CW3: Reachable chiptunes worker is adopted

#### UC-CW4: Unreachable chiptunes worker is replaced once

#### UC-CW5: A listener keeps music through a daemon restart

```gherkin
Scenario: Continue playback while the worker remains available
  Given a person is listening to music from a reachable Chiptunes worker
  And the daemon restarts before the worker's idle lease expires
  When the daemon resumes service
  Then music continues without starting a duplicate worker
```

#### UC-CW6: Reattach terminates unreachable chiptunes orphan

#### UC-CW7: Idle chiptunes worker exits after lease window

#### UC-CW8: Idle chiptunes worker stays alive within lease window

#### UC-DL1: Projects listing tolerates a registry entry that is not a project checkout

```
Given a project registry entry exists on disk and is not a TeleClaude project checkout, such as a person home
When the projects-with-todos listing runs
Then the listing succeeds and returns every existing registry entry in registry order, each under its display name
And the non-checkout entry carries an empty todo list
And no todo store is resolved, opened, or created for the non-checkout entry
```

#### UC-DL7: A registry change the daemon did not make reaches connected clients without a restart

```
Given the daemon is running with TUI clients connected
When an operator adopts a folder with `telec config project adopt` or edits the project registry by hand
Then within seconds every connected client receives a project list that reflects the change
And the daemon did not restart
```

#### UC-DL8: An add-project request adopts the folder and updates every connected client

```
Given the daemon is running with TUI clients connected
When a caller cleared to initialize projects asks the daemon to add a folder
Then the folder is adopted onto the project registry, created first when it did not exist
And the response names the adopted entry by its display name
And every connected client receives a project list that includes it
But when adoption fails the response carries the reason and a folder the request created is removed again
```

#### UC-DL3: Startup work added to a stage neither extends nor reorders the boot prefix

```
Given a startup stage carries work contributed by another bounded context
When startup runs
Then the documented stage order is unchanged
And the contributed work completes inside its own stage rather than deferring a later one
```

#### UC-DL5: Operations abandoned by a previous run do not abort the boot

```
Given durable operations were left queued or running when a previous daemon run stopped
When startup runs
Then the operations stage normalizes them to their stale outcome
And the post-adapter completion stage delivers each of those outcomes to its recorded caller
And startup proceeds to its running state
And no stage is skipped, reordered, or added
```

#### UC-DL9: Session startups left unfinished by a previous run neither abort nor hold the boot

```gherkin
Given session startups were left unfinished when a previous daemon run stopped
When the post-adapter completion stage runs
Then each of those startups is resumed or reported as `local/projects/teleclaude/spec/feature/agent_runtime/session-lifecycle` defines
And a resumed startup waits for its agent in the background, so the stage completes without waiting for any agent
And a fault while taking up one startup is recorded for that session and leaves the others and the boot unaffected
And no stage is skipped, reordered, or added
```

#### UC-DL10: Draining refuses new work before acceptance

```gherkin
Given an agent caller asks a draining daemon to begin new business work
When the request reaches a command ingress
Then the caller receives a retryable shutdown refusal before acknowledgment or business effects
And no operation receipt or session acceptance is reported for that refused request
And status reads and completions belonging to already acknowledged work remain available
```

#### UC-DL11: An acknowledged mutation settles before its dependencies stop

```gherkin
Given an agent caller has an acknowledged removal or another daemon-owned mutation in progress
When a human operator requests ordinary daemon shutdown
Then the mutation completes or reports its established failure after required compensation
And its durable outcome is settled before its storage, locks or completion dependencies are released
And shutdown does not cancel an active external effect and leave it running after its owner exits
```

#### UC-DL12: A preparation timeout preserves unfinished work and the shutdown still completes

```gherkin
Given an operator or commit-boundary maintenance requests ordinary stop or restart
And acknowledged work has not settled within the preparation observation window
When that window expires
Then the request reports that preparation did not complete
And the running daemon retains its draining state and the unfinished work's required resources
And the host service is neither forcibly terminated nor replaced by that request
And once that work settles the prepared daemon completes its own shutdown as UC-DL16 states
```

#### UC-DL13: Preparation belongs to the observed process

```gherkin
Given an agent operating the host has observed the running daemon's preparation capability and process instance
When it requests preparation and waits for completion
Then completion is accepted only from that same process instance
And an unsupported capability or replacement process produces a visible refusal before a preparation signal or service-manager replacement
```

#### UC-DL14: A command refused by a restarting daemon tells its caller to run it again

```gherkin
Given an agent runs a daemon-backed telec command while the daemon is draining or not reachable
When the command receives a shutdown refusal or cannot connect to the daemon
Then it exits non-zero with a message stating that nothing was accepted
And the message tells the caller to wait a fixed delay that spans a typical daemon restart and run the same command again, repeating while it is still refused
And the message states that no reminder can be set for the retry, because setting one is a request to the same daemon
And the message tells the caller to stop retrying once the daemon has stayed unavailable for several minutes, and to end its turn stating which command was not run
And the message names no machine fields from the refusal body
And a command that fails for any other reason carries no instruction to run it again
```

#### UC-DL15: A draining daemon is reported as draining

```gherkin
Given the running daemon has closed admission for preparation
When an agent or operator checks daemon health
Then the health report names the preparation phase, when preparation began, and the accepted work the daemon still holds
And a daemon whose admission is closed is reported degraded, never healthy
```

#### UC-DL16: A prepared daemon completes its own shutdown

```gherkin
Given the running daemon has reached the drained phase
When no termination from its lifecycle caller arrives within the bounded termination grace
Then the daemon completes its ordinary shutdown and exits on its own
And the service manager relaunches the service on its installed code
And admission never reopens in the prepared process before it exits
And a caller that terminates the daemon within the grace sees the ordinary stop or restart
```

#### UC-DL17: A long-lived task that ends is replaced, or the daemon restarts

```gherkin
Given the daemon is running with admission open
And an agent operating the daemon relies on a capability that a long-lived daemon task provides
When that task ends for any reason other than cancellation or the daemon's shutdown
Then the agent reading the daemon log finds which task ended, how it ended, and for a failure its traceback
And the task's supervisor starts a replacement after a backoff while the task's bounded restart budget lasts
And when the task cannot be replaced in place, or its restart budget is exhausted, the daemon log records the escalation and the daemon completes its ordinary shutdown
And the service manager relaunches the service on its installed code
And the agent never finds the capability silently absent while the daemon reports itself healthy
```

### Runtime-local coordination

Runtime-owned readiness coordination scopes a waiter to its target session and
launch identity. Registration precedes the action that can satisfy the waiter.
Managed launch identity originates before child execution and returns with the
normalized hook from that child. The runtime validates this correlation before
applying managed-start evidence; the current record alone does not establish
which launch produced an arriving hook.
Installing a new ordinary run and clearing its observed-start evidence are one
source mutation. A matching start writes that evidence conditionally against
the same run, and resumed catch-up reads that run's evidence. A hook without
launch context never acquires the current run's identity from the database;
an already-running process without that correlation retains its existing
timeout and inspection outcomes rather than establishing a new run's readiness.
An already persisted matching start can satisfy a resumed wait; another
session's start or a distinct compaction launch cannot satisfy it. Success,
timeout, cancellation and shutdown settle and release the registration under
the caller's existing launch or continuation contract. This ownership follows
`sdlc/policy/domain-ownership`.

Hook-outbox processing that awaits its runtime owner retains that completion
boundary before the hook is settled. Local readiness and continuations use
their owning runtime capability, independently of domain-notification
consumption. Command execution retains the command or operation owner's
acceptance and completion contract, as composed by
`local/projects/teleclaude/design/architecture/event-delivery`.

### Graceful admission and settlement

The service owns admission and draining across API, adapter, remote-command and
scheduled-work ingress. Acknowledged operations, session bootstraps and input
deliveries keep one owning scope through their effects and durable acknowledgments.
Completion ingress is admitted only for work that already holds that ownership;
daemon credentials alone confer no exemption. A refusal leaves an unaccepted
command either unconsumed or explicitly answered as refused.

The preparation observation window bounds the host caller's wait. Its expiry
neither releases a mutating worker's ownership nor turns an unfinished action into
success. The running service remains draining until acknowledged work reaches a
settled boundary, and the drained process then completes its shutdown whether or
not its caller is still observing it: a prepared process never stays alive closed
to business work. Existing restart recovery remains authoritative for a forced
termination or abrupt loss; an unfinished operation is not described as resumable
merely because it has a durable receipt.

This ownership boundary preserves the no-interference invariant
(`general/principle/trust-and-guardrails`); recorded outcomes retain their
evidence requirement (`general/principle/grounding`).

### Cross-context references

- **identity**: tokens are revalidated lazily at request time; lifecycle does not pre-validate. The startup-time token cache is empty — population happens on first auth check after the request surface is up.
- **config**: configuration is loaded at module import time; runtime settings are constructed once during service initialization and persisted via debounced writes thereafter. Lifecycle does not re-read effective configuration mid-run.
- **session_mirrors**: no direct dependency from lifecycle. The mirror worker is scheduled by the service AFTER startup returns; mirror extraction reacts to session-end events downstream and uses the native transcript file path captured at session end.
- **workflow** and **identity (v2)**: the workflow-bridge and identity-bridge tasks subscribe to v2 channels and translate envelopes into v1 cache invalidation; lifecycle's role is limited to ensuring the request surface (and therefore the push broadcaster) is up before these subscribers are running.
- **session_subscriptions** / **direct-conversation-links**: reconciliation of orphaned pending-through cursors for peer bundles runs once at startup inside the post-adapter completion stage.

## Known caveats

- **Cache warm is durable-storage-only.** The lifecycle does not match cached snapshots against live host panes. A session row marked active in storage with no corresponding host pane will appear in the cache until a downstream operation (poller watch, periodic cleanup) discovers the mismatch.
- **Orphan host-pane/workspace/tmpdir sweeps are amortized into the steady-state cleanup loop**, not into startup. The first periodic cleanup iteration runs immediately after startup completes, so the practical effect is sweep-on-boot — but it happens after the started flag is set and after the request surface is accepting traffic, not before.

- **A failure that recurs on every start becomes a relaunch cycle.** A supervised task that fails again after each replacement, and again after each relaunch, escalates on every run. The service manager's relaunch pacing bounds the cycle; the daemon log records every end and every escalation, and nothing ends the cycle until the cause is removed.
- **Supervision stops once shutdown preparation begins.** A long-lived task that ends while the daemon is draining or stopping is neither replaced nor escalated; the daemon already reports itself draining, and its own shutdown follows.
- **Per-session and per-client tasks are replaced on demand, not supervised.** Output pollers, per-session hook-outbox and inbound workers, and per-client senders are started again by their owners at the next demand — the poller watch, the next enqueue, the next message — so between one ending and that demand, the affected session or client waits.

- **The should-exit flag is the only clean-exit signal.** A request-surface task that exited because should-exit was set is treated as intentional and does NOT trigger restart. Anything else (raised exception, task done without should-exit) is treated as a crash.
- **Slow startup is a warning, not a failure.** Startup elapsed time at or beyond the slow-startup threshold (30s) emits a warning; the warm cache also emits a per-stage breakdown when warm takes 5s or more. Neither aborts the boot.
- **Background workers are started outside the lifecycle.** Lifecycle startup does NOT launch periodic cleanup, poller watch, the hook-outbox worker, the mirror worker, or the v2 bridges — those are launched by the service's start sequence after lifecycle startup returns. The split is deliberate: lifecycle owns the deterministic boot prefix; the service owns the steady-state worker set.
- **Chiptunes worker survives service restart, within bounds.** Its registry is persisted at the platform home so a surviving worker can be found after restart. Only a same-user Chiptunes worker is eligible for reattachment; a process that merely mentions the worker module is ignored. The service reattaches to a reachable worker and does not spawn a duplicate. An unreachable worker is terminated before at most one replacement is started. A worker with no daemon client past the idle-lease window exits on its own. Music continuity is bounded by worker reachability and that lease.

- **A timed-out stop ends in a relaunched daemon.** The service manager relaunches a daemon that completes its own shutdown, and the prepared process carries no record of whether its caller asked for a stop or a restart. Keeping the daemon down after a stop whose preparation timed out takes another `make stop` once it is back.

- **Post-settlement teardown is best-effort.** An ordinary task or component
  failure is reported with its identifier and traceback and does not prevent
  later cleanup attempts in the existing order, including storage closure before
  final lock release. Cancellation semantics and existing budgets are preserved;
  this isolation does not bypass admission closure or accepted-work settlement.
  A failed component is not reported as successfully closed, and lock release
  alone establishes neither successful resource closure nor process exit.
