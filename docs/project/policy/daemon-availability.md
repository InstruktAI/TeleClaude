---
description: 'The TeleClaude daemon must stay up; restarts must be brief and verified.'
visibility: 'public'
---

# Daemon Availability — Policy

## Rules

- The daemon is a 24/7 service; downtime is not acceptable outside controlled restarts.
<!-- planned-change:make-restart-ends-at-kickstart -->
- After a canonical-main change needing a restart, commit-boundary maintenance invokes `make restart` and records its health-checked terminal outcome; an agent does not repeat it. A separate agent-operated recovery invokes `make restart` and observes success, or verifies with `make status`.
<!-- change:make-restart-ends-at-kickstart -->
- `make restart` ends when the service manager accepts the restart. Nothing follows it: no wait, check, or other step runs after the restart inside the command, and it is the last action of any maintenance or recovery sequence that includes it. Its outcome records only that acceptance.
- After a canonical-main change needing a restart, commit-boundary maintenance invokes `make restart` as its final action; an agent does not repeat it. Agent-operated recovery invokes `make restart` the same way.
<!-- /planned-change:make-restart-ends-at-kickstart -->
- Daemon process-lifecycle observability is in-daemon: the janitor emits one `system.process.reaped` event per kill (queryable via `telec events`), and structured logs carry SIGTERM and shutdown attribution. Ad-hoc host probes (`dtrace`/`fs_usage`) installed outside `make` are not used.
<!-- planned-change:make-restart-ends-at-kickstart -->
- Verify key services after restart (API socket, API health/read endpoints, adapters).
<!-- change:make-restart-ends-at-kickstart -->
- Daemon health (API socket, API health/read endpoints, adapters) is verified by `make status`, a separate invocation that is never part of `make restart`. After a canonical-main activation, the standing integrator's log judgment establishes whether the restarted daemon came back healthy.
<!-- /planned-change:make-restart-ends-at-kickstart -->
- If Redis is configured for the event platform, startup must expose Redis reachability and pending recovery progress through daemon state or structured logs before continuing degraded; a silent healthy-but-no-Streams state is forbidden.
- `make stop` and `make restart` bring down the daemon and its managed launchd units only; they never signal an agent session, the tmux server, or a spawn-registry lease-holder. Sessions and leased detached workers (e.g. the chiptunes worker) outlive the daemon by design: sessions end only through the caller-driven path (see `general/principle/session-lifecycle`); leased workers are re-adopted via adopt-or-kill on the next start (see `project/design/process-lifecycle`).
- `make stop` is bounded and verified: SIGTERM the daemon, confirm exit within 30 seconds, then SIGKILL it if it has not exited. Termination targets the daemon and managed-unit pids only, never a process-group sweep.
- A leaked daemon-bound process — one with no live session and no registry lease — is reaped by the in-daemon janitor on the next start, never left to accumulate (see `project/design/process-lifecycle`).
- Every TeleClaude-installed launchd unit is in the managed set; no monitoring or helper unit runs independently of `make`.

## Rationale

- Users rely on the service continuously; unplanned downtime breaks active sessions and automation.
<!-- planned-change:make-restart-ends-at-kickstart -->
- Explicit restart + verification is the safest minimal-downtime path.
<!-- change:make-restart-ends-at-kickstart -->
- Explicit restart + separate verification is the safest minimal-downtime path.
- A restart can terminate the process that requested it, and a daemon in its first seconds is at its busiest. A check inside the restart measures that warm-up rather than whether the restart happened, and turns a successful restart into a failed maintenance record that holds up delivery.
<!-- /planned-change:make-restart-ends-at-kickstart -->

## Scope

- Applies to all local development and production operations of the TeleClaude daemon.

## Enforcement

- Use `make restart` only after changes that require it.
- Review recent logs with `instrukt-ai-logs teleclaude --since 2m` if stability is in doubt.
- If the daemon restarts unexpectedly, review the `system.process.reaped` event stream (`telec events`) and structured shutdown logs before taking action.
- A `make stop` that leaves the daemon or a managed launchd unit alive past 30 seconds, or that signals a session, tmux, or spawn-registry lease-holder pid, is a defect.

## Exceptions

- None.

## See Also

<!-- planned-change:make-restart-ends-at-kickstart -->
- docs/project/adr/0100-commit-maintenance-drains-after-hook-return.md — why the maintenance runner owns restart verification after Git returns.
<!-- change:make-restart-ends-at-kickstart -->
- docs/project/adr/0100-commit-maintenance-drains-after-hook-return.md — why commit-boundary maintenance drains in a detached runner after Git returns.
<!-- /planned-change:make-restart-ends-at-kickstart -->
