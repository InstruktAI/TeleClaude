---
description: 'The TeleClaude daemon must stay up; restarts must be brief and verified.'
visibility: 'public'
---

# Daemon Availability — Policy

## Rules

- The daemon is a 24/7 service; downtime is not acceptable outside controlled restarts.

- An install is a controlled restart. The daemon is down from before the install's first migration until its start on the new release; preparing the release happens while it serves, and publication of documentation and configuration schemas runs after the verified start, while it serves (`local/projects/teleclaude/design/architecture/installation`). The install succeeds only once the started daemon is verified serving the new release; initial provisioning — the bootstrap's install on a machine with no installed release and no daemon serving — replaces no daemon and completes without a start, which `telec app start` performs once the configuration is valid; an install into an existing installation whose daemon is stopped still ends with a verified start. An install that cannot establish the daemon stopped leaves it as it is and runs no migration. An install that fails after the stop before any migration started stops the daemon it started and returns to the previously active release and verifies its start; when that daemon cannot be stopped, the install leaves it running on the release it attempted. One that fails after a migration started leaves the daemon stopped with that reason recorded; `telec app status` reports each reason.

- `telec app start` and `telec app restart` first establish that the machine configuration loads; when it does not, they refuse with its finding and leave a running daemon running, because the daemon cannot boot on it.

<!-- planned-change:daemon-drain-ends-after-grace-window -->

- `telec app restart` prepares the running daemon before the service-manager action (`local/projects/teleclaude/policy/agent-service-control`) and ends when the service manager accepts the restart. Nothing follows the service-manager action inside the command: no wait, check, or other step runs after it there. Its outcome records that acceptance, the refused machine configuration or refused preparation that withheld the service-manager action, or a restart deferred to the daemon. A preparation that does not complete within its observation window is a deferred restart: the draining daemon completes the restart itself once its accepted work settles (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`), so a deferred restart is a successful outcome that owes no retry.

<!-- change:daemon-drain-ends-after-grace-window -->

- `telec app restart` prepares the running daemon before the service-manager action (`local/projects/teleclaude/policy/agent-service-control`) and ends when the service manager accepts the restart. Nothing follows the service-manager action inside the command: no wait, check, or other step runs after it there. Its outcome records that acceptance, or the refused machine configuration or refused preparation that withheld the service-manager action. Preparation ends with the daemon's grace window at the latest: accepted work still unsettled then is interrupted, the restart names it and proceeds, and a prepared daemon that does not end within its teardown bound is terminated (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`).

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

- An install replaces the daemon through a prepared stop and a verified start, never through a restart; an agent does not repeat a completed install. Agent-operated recovery outside an install uses `telec app restart`.

- Daemon process-lifecycle observability is in-daemon: the janitor emits one process-reaped event per kill (queryable via `telec events`), and structured logs carry SIGTERM and shutdown attribution. Ad-hoc host probes (`dtrace`/`fs_usage`) installed outside the installation are not used.

- Daemon health (API socket, API health/read endpoints, adapters, preparation phase) is verified by `telec app status`, a separate invocation that is never part of `telec app restart`. A daemon whose admission is closed is reported as draining — its phase, when preparation began, and the accepted work it still holds — and never as healthy. `telec app status` also names the active release, and the reason and time an install last refused to stop the daemon, left it stopped, or left it without a verified start, until a later start verifies. After an install, the standing integrator's log judgment establishes whether the runtime behaves correctly on the installed release.

- Only a core dependency stops the daemon; which dependencies are core, and how a failed start ends the process, are owned by `local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`. An optional component that fails — one project's workflow store, a UI adapter, chiptunes — is logged as an error and left out. Until it serves again, `telec app status` reports the daemon degraded and names each such component with its reason; a component that cannot recover while the daemon runs stays reported until the daemon restarts, and chiptunes stays reported through a deferred provisioning until that provisioning succeeds. A degraded project is a record about that project: it is reported only to a caller whose reach admits the project, and to any other caller it is indistinguishable from a project that serves (`local/projects/teleclaude/spec/feature/identity/data-visibility`). `telec app status` reads the daemon's health as the caller who invoked it. A UI adapter's reason names the type of its start failure, never the failure's message; the message stays in the daemon log.

- If Redis is configured for the event platform, startup must expose Redis reachability and pending recovery progress through daemon state or structured logs before continuing degraded; a silent healthy-but-no-Streams state is forbidden.

- `telec app stop` and `telec app restart` bring down the daemon and its managed launchd units only; they never signal an agent session, the tmux server, the local Redis, or a spawn-registry lease-holder. Sessions and leased detached workers (e.g. the chiptunes worker) outlive the daemon by design: sessions end only through the caller-driven path (see `general/principle/session-lifecycle`); leased workers are re-adopted via adopt-or-kill on the next start (see `local/projects/teleclaude/design/process-lifecycle`).

<!-- planned-change:daemon-drain-ends-after-grace-window -->

- `telec app stop` prepares the running daemon before stopping it. A preparation that does not complete within its observation window is reported and leaves the daemon running and draining; it is never forcibly terminated by that stop, and once its accepted work settles the daemon completes its own shutdown and the service manager relaunches it. Once the daemon is prepared, the stop is bounded and verified: SIGTERM the daemon, confirm exit within 30 seconds, then SIGKILL it if it has not exited. Termination targets the daemon and managed-unit pids only, never a process-group sweep.

<!-- change:daemon-drain-ends-after-grace-window -->

- `telec app stop` prepares the running daemon before stopping it. Preparation ends with the daemon's grace window at the latest; accepted work still unsettled then is interrupted, and the stop names it. Once preparation has ended, the stop is bounded and verified: SIGTERM the daemon, confirm exit within 30 seconds, then SIGKILL it if it has not exited. A prepared daemon that answers neither with an acknowledgment nor by ending within its grace window and teardown bound is terminated the same way. Termination targets the daemon and managed-unit pids only, never a process-group sweep.

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

<!-- planned-change:daemon-drain-ends-after-grace-window -->

- `telec app stop` records its outcome where a caller names a location for it, so a caller never infers the daemon's state from an exit status: stopped, meaning no daemon process remains and its service manager will not relaunch it, whether or not this stop had to terminate it; stopped with a managed-unit cleanup failure; withheld while the daemon drains; or withheld, with its reason. The record states the daemon's state after the stop, so a caller acts on that state rather than on the command's exit status. Once preparation allows it, `telec app stop` issues its service manager's stop whatever state the daemon starts from.

<!-- change:daemon-drain-ends-after-grace-window -->

- `telec app stop` records its outcome where a caller names a location for it, so a caller never infers the daemon's state from an exit status: stopped, meaning no daemon process remains and its service manager will not relaunch it, whether or not this stop had to terminate it; stopped with a managed-unit cleanup failure; or withheld, with its reason. The record states the daemon's state after the stop, so a caller acts on that state rather than on the command's exit status. Once preparation allows it, `telec app stop` issues its service manager's stop whatever state the daemon starts from.

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

- A leaked daemon-bound process — one with no live session and no registry lease — is reaped by the in-daemon janitor on the next start, never left to accumulate (see `local/projects/teleclaude/design/process-lifecycle`).
- Every TeleClaude-installed launchd unit is in the managed set, except the units that outlive the daemon by design: the tmux server and the local Redis, whose unit the installation deploys and which commands and periodic jobs publish to while the daemon is down; no monitoring or helper unit runs independently of the installation's lifecycle.

## Rationale

- Users rely on the service continuously; unplanned downtime breaks active sessions and automation.
- An optional component's failure denies only what that component serves. Letting it stop the daemon turns one project's refusal into an outage of every session, hook, wake and relay on the computer.
- A failed daemon that stays alive is worse than one that exits: the service manager relaunches only a process that ended, and nothing reports the outage while the process lives.
- Explicit restart + separate verification is the safest minimal-downtime path.
- A restart can terminate the process that requested it, and a daemon in its first seconds is at its busiest. A check inside the restart measures that warm-up rather than whether the restart happened, and turns a successful restart into a failed maintenance record that holds up delivery.

- A daemon that keeps serving while an install migrates the state it runs on reads state its loaded code may not understand. Keeping it safe then needs every writer ordered around the restart or gated on what the old process can read, and a single writer that escapes the ordering leaves the daemon refusing its own configuration. With the daemon stopped there is no older reader to protect, so the steps need only their own dependency order. Preparing a release replaces nothing the daemon runs on, and publication reads only the installed commit, so both run while it serves without holding it down. The remaining cost is downtime for the other steps: sessions, leased workers and the hook outbox already outlive a stopped daemon, and callers already meet a refusal that tells them to retry.

- The install runs outside the daemon it stops, so it outlives the stop and can wait out the started daemon's warm-up within a bound before it judges the start. An install that reported success without that verification would leave a daemon that never came back to be discovered by whoever next needed it, and a reason recorded where `telec app status` reads it reaches that person first.

- A service manager that relaunches the daemon on exit keeps doing so for a unit that is merely disabled; only its explicit stop cancels a relaunch it has scheduled. A stop that skipped that call for an already-disabled unit could report a stopped daemon while a relaunch was pending, and an install would then migrate under a daemon about to come back.

<!-- planned-change:daemon-drain-ends-after-grace-window -->

- Stopping a daemon while acknowledged work is still effecting leaves that work half-done with its owner gone. Preparation settles that work first, and a daemon whose preparation has not completed is safer left draining than forced down (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`).

<!-- change:daemon-drain-ends-after-grace-window -->

- Stopping a daemon while acknowledged work is still effecting leaves that work half-done with its owner gone, so preparation gives that work a grace window to settle first. Work still unsettled after every request deadline the daemon enforces has passed is not finishing on its way out; holding the daemon for it makes every stop and restart wait on its slowest stuck unit, and a hang then leaves the computer with no ordinary way back. Restart recovery already owns work an abrupt loss interrupts, so ending at the window records that work as interrupted instead of giving up the computer's availability for it (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`).

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

<!-- planned-change:daemon-drain-ends-after-grace-window -->

- A drained daemon that waits for its caller to return is an outage nobody owns: callers time out, crash or move on, and a prepared process never reopens admission. Completing its own shutdown once its work has settled keeps the guarantee that unsettled work is never forced down without making availability depend on a caller coming back. A health check that reports such a daemon as healthy hides that outage from everyone who could end it.

<!-- change:daemon-drain-ends-after-grace-window -->

- A drained daemon that waits for its caller to return is an outage nobody owns: callers time out, crash or move on, and a prepared process never reopens admission. Completing its own shutdown once its work has settled or its grace window has ended keeps availability from depending on a caller coming back, and a host stop or restart that terminates a daemon unable to end itself keeps it from depending on the daemon. A health check that reports such a daemon as healthy hides that outage from everyone who could end it.

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

- A start failure's message can carry the adapter's configured credential, so health and status, which reach callers beyond the operator, show only its type.

## Scope

- Applies to all local development and production operations of the TeleClaude daemon.

## Enforcement

<!-- planned-change:daemon-drain-ends-after-grace-window -->

- A `telec app stop` that leaves a prepared daemon or a managed launchd unit alive past 30 seconds after preparation completed, that forcibly terminates a daemon whose preparation has not completed, or that signals a session, tmux, or spawn-registry lease-holder pid, is a defect.

<!-- change:daemon-drain-ends-after-grace-window -->

- A `telec app stop` or `telec app restart` that leaves a daemon alive past its grace window, its teardown bound and the stop's bounded exit wait, that terminates a daemon before its grace window has ended, or that signals a session, tmux, or spawn-registry lease-holder pid, is a defect.

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

<!-- planned-change:daemon-drain-ends-after-grace-window -->

- A daemon alive with admission closed after its accepted work has settled and its termination grace has passed is a defect.

<!-- change:daemon-drain-ends-after-grace-window -->

- A daemon alive with admission closed after its accepted work has settled or its grace window has ended, and its termination grace has passed, is a defect.

<!-- /planned-change:daemon-drain-ends-after-grace-window -->

- The installation inspector's post-install log judgment catches a startup that aborted on an optional component's failure and a process left alive without its request surface after a failed start; either is a defect.

## Exceptions

- None.

## See Also

- docs/local/adr/0124-maintenance-replaces-the-daemon-inside-a-stopped-window.md — why the daemon is stopped instead of ordering steps around a live process.
- docs/local/adr/0127-maintenance-runs-serving-tolerant-steps-after-the-verified-start.md — why the steps that replace nothing the daemon runs on run after the verified start.
- docs/local/design/architecture/installation.md — the install act this policy governs.
- docs/local/adr/0143-teleclaude-runs-its-own-local-redis-on-every-computer.md — why the local Redis outlives the daemon.
