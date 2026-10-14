---
description: 'The TeleClaude daemon must stay up; restarts must be brief and verified.'
visibility: 'public'
---

# Daemon Availability — Policy

## Rules

- The daemon is a 24/7 service; downtime is not acceptable outside controlled restarts.

- A maintenance run that replaces the daemon is a controlled restart. The daemon is down for the length of that run: it settles its accepted work and stops before the run's first step, no step runs while it serves, and it starts again after the last step (`local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`). The run succeeds only once the started daemon is verified recovered. A run that cannot establish the daemon stopped leaves it as it is and runs no step, and a run whose start does not verify leaves the daemon with that reason recorded; `make status` reports either reason.

- `make start` and `make restart` first establish that the machine configuration loads; when it does not, they refuse with its finding and leave a running daemon running, because the daemon cannot boot on it.

- `make restart` prepares the running daemon before the service-manager action (`local/projects/teleclaude/policy/agent-service-control`) and ends when the service manager accepts the restart. Nothing follows the service-manager action inside the command: no wait, check, or other step runs after it there. Its outcome records that acceptance, the refused machine configuration or refused preparation that withheld the service-manager action, or a restart deferred to the daemon. A preparation that does not complete within its observation window is a deferred restart: the draining daemon completes the restart itself once its accepted work settles (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`), so a deferred restart is a successful outcome that owes no retry.

- A maintenance run replaces the daemon through `make stop` and `make start`, never through `make restart`; an agent does not repeat completed maintenance. Agent-operated recovery outside a maintenance run uses `make restart`.

- Daemon process-lifecycle observability is in-daemon: the janitor emits one process-reaped event per kill (queryable via `telec events`), and structured logs carry SIGTERM and shutdown attribution. Ad-hoc host probes (`dtrace`/`fs_usage`) installed outside `make` are not used.

- Daemon health (API socket, API health/read endpoints, adapters, preparation phase) is verified by `make status`, a separate invocation that is never part of `make restart`. A daemon whose admission is closed is reported as draining — its phase, when preparation began, and the accepted work it still holds — and never as healthy. `make status` also names the reason, and the time, a maintenance run last refused to open its window or left the daemon without a verified start, until a later run verifies one. After a canonical-main activation, the standing integrator's log judgment establishes whether the runtime behaves correctly after the maintenance run.

- If Redis is configured for the event platform, startup must expose Redis reachability and pending recovery progress through daemon state or structured logs before continuing degraded; a silent healthy-but-no-Streams state is forbidden.
- `make stop` and `make restart` bring down the daemon and its managed launchd units only; they never signal an agent session, the tmux server, or a spawn-registry lease-holder. Sessions and leased detached workers (e.g. the chiptunes worker) outlive the daemon by design: sessions end only through the caller-driven path (see `general/principle/session-lifecycle`); leased workers are re-adopted via adopt-or-kill on the next start (see `local/projects/teleclaude/design/process-lifecycle`).

- `make stop` prepares the running daemon before stopping it. A preparation that does not complete within its observation window is reported and leaves the daemon running and draining; it is never forcibly terminated by that stop, and once its accepted work settles the daemon completes its own shutdown and the service manager relaunches it. Once the daemon is prepared, the stop is bounded and verified: SIGTERM the daemon, confirm exit within 30 seconds, then SIGKILL it if it has not exited. Termination targets the daemon and managed-unit pids only, never a process-group sweep.

- `make stop` records its outcome where a caller names a location for it, because `make` reports every failing recipe with the same status: stopped, meaning no daemon process remains and its service manager will not relaunch it, whether or not this stop had to terminate it; stopped with a managed-unit cleanup failure; withheld while the daemon drains; or withheld, with its reason. The record states the daemon's state after the stop, so a caller acts on that state rather than on the command's exit status. Once preparation allows it, `make stop` issues its service manager's stop whatever state the daemon starts from.

- A leaked daemon-bound process — one with no live session and no registry lease — is reaped by the in-daemon janitor on the next start, never left to accumulate (see `local/projects/teleclaude/design/process-lifecycle`).
- Every TeleClaude-installed launchd unit is in the managed set; no monitoring or helper unit runs independently of `make`.

## Rationale

- Users rely on the service continuously; unplanned downtime breaks active sessions and automation.
- Explicit restart + separate verification is the safest minimal-downtime path.
- A restart can terminate the process that requested it, and a daemon in its first seconds is at its busiest. A check inside the restart measures that warm-up rather than whether the restart happened, and turns a successful restart into a failed maintenance record that holds up delivery.

- A daemon that keeps serving while maintenance changes the code, dependencies, configuration and service definitions it runs on reads state its loaded code may not understand. Keeping it safe then needs every writer ordered around the restart or gated on what the old process can read, and a single writer that escapes the ordering leaves the daemon refusing its own configuration. With the daemon stopped there is no older reader to protect, so the steps need only their own dependency order. The cost is downtime for the length of the run: sessions, leased workers and the hook outbox already outlive a stopped daemon, and callers already meet a refusal that tells them to retry.

- Maintenance runs detached from the daemon it stops, so it outlives the stop and can wait out the started daemon's warm-up within a bound before it judges the start. A run that reported success without that verification would leave a daemon that never came back to be discovered by whoever next needed it, and a reason recorded where `make status` reads it reaches that person first.

- A service manager that relaunches the daemon on exit keeps doing so for a unit that is merely disabled; only its explicit stop cancels a relaunch it has scheduled. A stop that skipped that call for an already-disabled unit could report a stopped daemon while a relaunch was pending, and maintenance would then run against a daemon about to come back.

- Stopping a daemon while acknowledged work is still effecting leaves that work half-done with its owner gone. Preparation settles that work first, and a daemon whose preparation has not completed is safer left draining than forced down (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`).

- A drained daemon that waits for its caller to return is an outage nobody owns: callers time out, crash or move on, and a prepared process never reopens admission. Completing its own shutdown once its work has settled keeps the guarantee that unsettled work is never forced down without making availability depend on a caller coming back. A health check that reports such a daemon as healthy hides that outage from everyone who could end it.

## Scope

- Applies to all local development and production operations of the TeleClaude daemon.

## Enforcement

- Use `make restart` only after changes that require it.
- Review recent logs with `instrukt-ai-logs teleclaude --since 2m` if stability is in doubt.
- If the daemon restarts unexpectedly, review the process-reaped event stream (`telec events`) and structured shutdown logs before taking action.

- A `make stop` that leaves a prepared daemon or a managed launchd unit alive past 30 seconds after preparation completed, that forcibly terminates a daemon whose preparation has not completed, or that signals a session, tmux, or spawn-registry lease-holder pid, is a defect.

- A daemon alive with admission closed after its accepted work has settled and its termination grace has passed is a defect.

## Exceptions

- None.

## See Also

- docs/local/adr/0100-commit-maintenance-drains-after-hook-return.md — why commit-boundary maintenance drains in a detached runner after Git returns.
- docs/local/adr/0124-maintenance-replaces-the-daemon-inside-a-stopped-window.md — why a maintenance run stops the daemon instead of ordering its steps around a live process.
