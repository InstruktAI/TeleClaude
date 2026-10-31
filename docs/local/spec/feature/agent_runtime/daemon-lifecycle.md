---
description: "The long-running agent_runtime service process lifecycle — single-instance lock, staged startup (storage → operations → session cache warm → adapters → event platform → request surface → projects cache warm), shutdown ordering, and the request-surface restart loop that keeps the service's external surface alive across crashes."
visibility: 'public'
---

# Daemon Lifecycle — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

The agent_runtime bounded context is hosted by a single long-running service process per computer. This spec covers the deterministic startup and shutdown ordering of that process, and the recovery loop that re-launches the embedded request surface if it exits unexpectedly. The webhook ingress listener, where the daemon serves the ingress, belongs to the same recovery boundary as the API task. Everything that binds per-session machinery (output polling, host-pane orchestration, listeners, conversation links, hook ingest, mirrors) into one runtime hangs off of this lifecycle: it warms the in-memory caches that other surfaces read from, reconciles deliveries that might have been in flight when the previous process died, and starts the background workers that maintain liveness afterwards.

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

Startup separates core dependencies from optional components. The
single-instance lock, configuration, storage, the operations service, the event
platform and the request surface are core: a failure among them that is not
retryable, or exhausts its retries, ends startup. An optional component — a UI
adapter, chiptunes, one project's workflow store — that fails is logged as an
error, recorded as degraded and left out; startup continues, and its reporting
is owned by `local/projects/teleclaude/policy/daemon-availability`.

A startup that ends runs the ordinary stop, releases the lock, and then ends
the process with a non-zero status without waiting for worker threads.

<!-- planned:daemon-drain-ends-after-grace-window -->

An ordinary stop ends the process once its teardown completes or its teardown
bound expires, without waiting for worker threads: a worker thread blocked
inside unsettled work never keeps a stopped daemon alive
(`local/projects/teleclaude/policy/daemon-availability`).
<!-- /planned:daemon-drain-ends-after-grace-window -->

A failure resuming a prior session startup is recorded for that session and
does not block recovery of other sessions or daemon startup completion.

### Use cases

#### Staged startup ordering

Storage migration and initialization precede operations startup and local source
materialization. Adapters receive the local session state their startup
requires. Domain-event publication is ready before producers can emit, and
each required consumer's progress is established before the source activity it
must observe. Work contributed to a stage completes within that stage and does
not add or reorder the boot prefix. Registering or scheduling a reader alone
does not establish that handover.
The producer and reader positions for both event source streams are prepared
independently of adapter startup. Handler execution remains gated on its own
dependencies, including request-surface binding where required.

A configured event Redis that does not answer never stops startup
(`local/projects/teleclaude/policy/daemon-availability`). Before startup
continues, the daemon records and logs which scope's Redis did not answer.
While that lasts, the daemon's readiness answer names the Redis that does not
answer, and an unanswering Redis alone never makes it report the daemon as not
serving; draining is reported as it is at any other time. What the event consumers on that Redis do while
it is away and once it answers belongs to
`local/projects/teleclaude/design/architecture/event-delivery`.

Before adapters, pollers or conversation delivery emit new output, startup
reconciles durable input, transcript-binding, generation, peer-cursor and
send-intent state. Each existing session has a pre-cutover generation boundary;
restart rebuilds scheduling from durable rows, while agent panes and native
transcripts remain authoritative for work that continued during the outage.

The request surface is constructed before its event callbacks are wired, and
its listener is bound before consumers that call it execute. Source seeding and
live session materialization share an explicit coverage handover before the
runtime declares startup complete. The handover reconciles current source
state through the cache owner under
`local/projects/teleclaude/design/architecture/cache`; it does not publish
previously captured startup rows after newer live materialization.

Post-adapter reconciliation, request-surface recovery and project warmup retain
their owner contracts. The post-adapter completion stage finishes before the
request surface starts; recovery of each included task remains with its owner.
Startup remains idempotent and reports completion and slow stages through the
lifecycle's configured observations. These readiness boundaries follow
`sdlc/principle/architectural-defaults` and `sdlc/policy/domain-ownership`.

#### UC-DL6: Post-adapter completion tasks

#### UC-DL2 — Turn delivery state is reconciled before adapters can emit output

#### An operator can stop the daemon without losing accepted work

<!-- planned-change:daemon-drain-ends-after-grace-window -->

```gherkin
Given a human operator needs to stop or restart the daemon while acknowledged work is active
When ordinary shutdown begins
Then new work is refused and acknowledged work settles or reaches a durable recovery boundary before its required dependencies stop
And independently running agent turns continue without being terminated
```

<!-- change:daemon-drain-ends-after-grace-window -->

```gherkin
Given a human operator needs to stop or restart the daemon while acknowledged work is active
When ordinary shutdown begins
Then new work is refused and acknowledged work that settles within the grace window settles before its required dependencies stop
And work still unsettled when the grace window ends is never reported as successful
And independently running agent turns continue without being terminated
```

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

#### UC-DL4: Shutdown without active playback avoids invalid cancellation

```gherkin
Given the service has no active playback generation to cancel
When a human operator stops the service
Then shutdown completes without reporting a playback-cancellation validation failure
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

#### UC-DL1: An operator can list registered homes without treating them as projects

```
Given an operator needs the projects-with-todos listing
And a registered entry is not a TeleClaude project checkout, such as a person home
When they list the registered entries
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

#### UC-DL5: Operations abandoned by a previous run do not abort the boot

#### UC-DL9: An operator can restart the daemon when session recovery fails

```gherkin
Given a previous daemon run left one or more session startups unfinished
When an operator restarts the daemon
Then startup completes without waiting for resumed session agents
And a failure recovering one session does not block other startup work or daemon startup completion
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

<!-- planned-change:daemon-drain-ends-after-grace-window -->

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
And once that work settles the prepared daemon completes its own shutdown
```

<!-- change:daemon-drain-ends-after-grace-window -->

```gherkin
Given an agent caller has an acknowledged removal or another daemon-owned mutation in progress
When a human operator requests ordinary daemon shutdown
And the mutation settles within the grace window
Then the mutation completes or reports its established failure after required compensation
And its durable outcome is settled before its storage, locks or completion dependencies are released
And shutdown does not cancel an active external effect and leave it running after its owner exits
```

#### UC-DL12: A stop or restart completes when accepted work does not settle

```gherkin
Given an operator or the install act requests an ordinary stop or restart
And acknowledged work has not settled when the grace window ends
When the window ends
Then the daemon stops waiting for that work and ends
And the stop or restart completes and names the work the daemon interrupted
And the interrupted work is never reported as successful and is never replayed
And each operation the cutoff interrupted reaches its caller as interrupted once the daemon runs again
And agent sessions keep running
```

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

#### UC-DL13: Preparation belongs to the observed process

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

#### UC-DL17: An agent can detect and recover an unexpectedly ended daemon task

```gherkin
Given an agent operating the daemon relies on a capability provided by a long-lived task
And the daemon is running with admission open
When that task ends for any reason other than cancellation or the daemon's shutdown
Then the agent reading the daemon log finds which task ended, how it ended, and for a failure its traceback
And the task's supervisor starts a replacement after a backoff while the task's bounded restart budget lasts
And when the task cannot be replaced in place, or its restart budget is exhausted, the daemon log records the escalation and the daemon completes its ordinary shutdown
And the service manager relaunches the service on its installed code
And the agent never finds the capability silently absent while the daemon reports itself healthy
```

#### UC-DL18: An operator can restart the daemon with chiptunes turned off

```gherkin
Given an operator has chiptunes turned off
And other startup work is still writing the daemon's records while the daemon turns chiptunes off
When an operator restarts the daemon
Then startup completes and the daemon serves
And the service manager does not relaunch it
```

#### UC-DL19: A person keeps using their computer while its cluster Redis is unreachable

```gherkin
Given a person works with TeleClaude on a computer whose cluster Redis does not answer
When the daemon starts, or the cluster Redis stops answering while the daemon serves
Then the daemon keeps serving the person's sessions and commands on that computer
And the cluster Redis being away neither stops nor restarts the daemon
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

<!-- planned-change:daemon-drain-ends-after-grace-window -->

The preparation observation window bounds the host caller's wait. Its expiry
neither releases a mutating worker's ownership nor turns an unfinished action into
success. The running service remains draining until acknowledged work reaches a
settled boundary, and the drained process then completes its shutdown whether or
not its caller is still observing it: a prepared process never stays alive closed
to business work. Existing restart recovery remains authoritative for a forced
termination or abrupt loss; an unfinished operation is not described as resumable
merely because it has a durable receipt.

<!-- change:daemon-drain-ends-after-grace-window -->

The grace window bounds settlement. It opens when admission closes and lasts at
least the longest request deadline the daemon enforces plus a margin, so ordinary
in-flight requests settle inside it; every completion dependency keeps running
through it. Accepted work that settles inside the window settles before its
dependencies stop, and the drained process then completes its shutdown whether
or not its caller is still observing it: a prepared process never stays alive
closed to business work. When the window ends with work still held, the daemon
logs the work it holds, stops waiting for it and ends; the host caller learns
which work was interrupted. The cutoff neither turns an unfinished action into
success nor replays it. Existing restart recovery owns interrupted work as it
owns any forced termination or abrupt loss: an operation still unfinished is
recorded stale with its reason when the daemon starts again, and its outcome is
delivered to its caller (UC-DL5). An unfinished operation is not described as
resumable merely because it has a durable receipt. A host stop or restart
terminates a daemon that has not ended within the grace window and its teardown
bound, so the stop or restart completes even when the daemon cannot end itself
(`local/projects/teleclaude/policy/daemon-availability`).

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

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

<!-- planned-change:daemon-drain-ends-after-grace-window -->

- **A timed-out stop ends in a relaunched daemon.** The service manager relaunches a daemon that completes its own shutdown, and the prepared process carries no record of whether its caller asked for a stop or a restart. Keeping the daemon down after a stop whose preparation timed out takes another `make stop` once it is back.

<!-- change:daemon-drain-ends-after-grace-window -->

- **A cutoff can interrupt an effect that already reached its recipient.** Work interrupted at the end of the grace window may have delivered part of its effect, such as a chat message sent before its outcome was recorded. Its owner's restart recovery reports it as interrupted rather than repeating it, so a recipient can hold an effect whose owner records it unfinished.

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

- **Post-settlement teardown is best-effort.** An ordinary task or component
  failure is reported with its identifier and traceback and does not prevent
  later cleanup attempts in the existing order, including storage closure before
  final lock release. Cancellation semantics and existing budgets are preserved;
  this isolation does not bypass admission closure or accepted-work settlement.
  A failed component is not reported as successfully closed, and lock release
  alone establishes neither successful resource closure nor process exit.
