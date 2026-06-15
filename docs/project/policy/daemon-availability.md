---
description: 'The TeleClaude daemon must stay up; restarts must be brief and verified.'
visibility: 'public'
---

# Daemon Availability — Policy

## Rules

- The daemon is a 24/7 service; downtime is not acceptable outside controlled restarts.
- After any change needing a restart, call `make restart` and observe success, or verify with `make status`.
- Daemon process-lifecycle observability is in-daemon: the janitor emits one `system.process.reaped` event per kill (queryable via `telec events`), and structured logs carry SIGTERM and shutdown attribution. Ad-hoc host probes (`dtrace`/`fs_usage`) installed outside `make` are not used.
- Verify key services after restart (API socket, API health/read endpoints, adapters).
- If Redis is configured for the event platform, startup must expose Redis reachability and pending recovery progress through daemon state or structured logs before continuing degraded; a silent healthy-but-no-Streams state is forbidden.
- `make stop` and `make restart` bring down the daemon and its managed launchd units only; they never signal an agent session, the tmux server, or a spawn-registry lease-holder. Sessions and leased detached workers (e.g. the chiptunes worker) outlive the daemon by design: sessions end only through the caller-driven path (see `general/principle/session-lifecycle`); leased workers are re-adopted via adopt-or-kill on the next start (see `project/design/process-lifecycle`).
- `make stop` is bounded and verified: SIGTERM the daemon, confirm exit within 30 seconds, then SIGKILL it if it has not exited. Termination targets the daemon and managed-unit pids only, never a process-group sweep.
- A leaked daemon-bound process — one with no live session and no registry lease — is reaped by the in-daemon janitor on the next start, never left to accumulate (see `project/design/process-lifecycle`).
- Every TeleClaude-installed launchd unit is in the managed set; no monitoring or helper unit runs independently of `make`.

## Rationale

- Users rely on the service continuously; unplanned downtime breaks active sessions and automation.
- Explicit restart + verification is the safest minimal-downtime path.

## Scope

- Applies to all local development and production operations of the TeleClaude daemon.

## Enforcement

- Use `make restart` only after changes that require it.
- Review recent logs with `instrukt-ai-logs teleclaude --since 2m` if stability is in doubt.
- If the daemon restarts unexpectedly, review the `system.process.reaped` event stream (`telec events`) and structured shutdown logs before taking action.
- A `make stop` that leaves the daemon or a managed launchd unit alive past 30 seconds, or that signals a session, tmux, or spawn-registry lease-holder pid, is a defect.

## Exceptions

- None.
