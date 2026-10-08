---
description: 'The TeleClaude daemon must stay up; restarts must be brief and verified.'
visibility: 'public'
---

# Daemon Availability — Policy

## Rules

- The daemon is a 24/7 service; downtime is not acceptable outside controlled restarts.

- `make restart` prepares the running daemon before the service-manager action (`local/projects/teleclaude/policy/agent-service-control`) and ends when the service manager accepts the restart. Nothing follows the service-manager action: no wait, check, or other step runs after it inside the command, and `make restart` is the last action of any maintenance or recovery sequence that includes it. Its outcome records that acceptance, or the refused or incomplete preparation that withheld the service-manager action.

- After a canonical-main change needing a restart, commit-boundary maintenance invokes `make restart` as its final action; an agent does not repeat it. Agent-operated recovery invokes `make restart` the same way.
- Daemon process-lifecycle observability is in-daemon: the janitor emits one process-reaped event per kill (queryable via `telec events`), and structured logs carry SIGTERM and shutdown attribution. Ad-hoc host probes (`dtrace`/`fs_usage`) installed outside `make` are not used.
- Daemon health (API socket, API health/read endpoints, adapters) is verified by `make status`, a separate invocation that is never part of `make restart`. After a canonical-main activation, the standing integrator's log judgment establishes whether the restarted daemon came back healthy.
- If Redis is configured for the event platform, startup must expose Redis reachability and pending recovery progress through daemon state or structured logs before continuing degraded; a silent healthy-but-no-Streams state is forbidden.
- `make stop` and `make restart` bring down the daemon and its managed launchd units only; they never signal an agent session, the tmux server, or a spawn-registry lease-holder. Sessions and leased detached workers (e.g. the chiptunes worker) outlive the daemon by design: sessions end only through the caller-driven path (see `general/principle/session-lifecycle`); leased workers are re-adopted via adopt-or-kill on the next start (see `local/projects/teleclaude/design/process-lifecycle`).

- `make stop` prepares the running daemon before stopping it. A preparation that does not complete within its observation window is reported and leaves the daemon running and draining; it is never forcibly terminated by that stop. Once the daemon is prepared, the stop is bounded and verified: SIGTERM the daemon, confirm exit within 30 seconds, then SIGKILL it if it has not exited. Termination targets the daemon and managed-unit pids only, never a process-group sweep.

- A leaked daemon-bound process — one with no live session and no registry lease — is reaped by the in-daemon janitor on the next start, never left to accumulate (see `local/projects/teleclaude/design/process-lifecycle`).
- Every TeleClaude-installed launchd unit is in the managed set; no monitoring or helper unit runs independently of `make`.

## Rationale

- Users rely on the service continuously; unplanned downtime breaks active sessions and automation.
- Explicit restart + separate verification is the safest minimal-downtime path.
- A restart can terminate the process that requested it, and a daemon in its first seconds is at its busiest. A check inside the restart measures that warm-up rather than whether the restart happened, and turns a successful restart into a failed maintenance record that holds up delivery.

- Stopping a daemon while acknowledged work is still effecting leaves that work half-done with its owner gone. Preparation settles that work first, and a daemon whose preparation has not completed is safer left draining than forced down (`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`).

## Scope

- Applies to all local development and production operations of the TeleClaude daemon.

## Enforcement

- Use `make restart` only after changes that require it.
- Review recent logs with `instrukt-ai-logs teleclaude --since 2m` if stability is in doubt.
- If the daemon restarts unexpectedly, review the process-reaped event stream (`telec events`) and structured shutdown logs before taking action.

- A `make stop` that leaves a prepared daemon or a managed launchd unit alive past 30 seconds after preparation completed, that forcibly terminates a daemon whose preparation has not completed, or that signals a session, tmux, or spawn-registry lease-holder pid, is a defect.

## Exceptions

- None.

## See Also

- docs/local/adr/0100-commit-maintenance-drains-after-hook-return.md — why commit-boundary maintenance drains in a detached runner after Git returns.
