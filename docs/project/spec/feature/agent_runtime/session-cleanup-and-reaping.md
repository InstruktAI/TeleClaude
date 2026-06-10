---
description: 'agent_runtime — terminate a session, free its host-pane + workspace + tmpdir resources, sweep orphans, and replay close-requested events for sessions whose channel cleanup never completed.'
visibility: 'public'
---

# Session Cleanup and Reaping — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The cleanup half of agent_runtime session lifecycle. Where `session-lifecycle` accepts a close request, this surface performs it: token revocation, host-pane termination, conversation-link teardown, listener cleanup, adapter channel deletion, workspace removal, per-session tmpdir removal, escalation teardown, inbound expiry, and the final `closing -> closed` lifecycle write.

It also reconciles the gap between what durable storage believes and what the system holds: stale sessions (storage-active but host-pane-gone), orphan host-pane sessions (TeleClaude-prefixed host pane with no storage row), orphan workspace directories (UUID-named directory under the workspace base with no storage row), and orphan per-session tmpdirs (UUID-named subdirectory under the configured tmpdir base, not bound to a live session).

Finally, it provides the recently-closed replay mechanism: a sweep that re-emits a session-close request for closed sessions whose adapter channel reference is still set — recovering channel-deletion work that was dropped across a service restart.

The cleanup loop runs on the maintenance service tick (every hour by default). An end-session request reaches the termination flow synchronously via the command service.

## Canonical fields

### Use cases

#### terminate-session — happy path

```
Given a non-closed session row exists for session_id
And the caller invokes terminate-session for the session with a reason
When the cleanup begins
Then the session id is added to the in-flight cleanup set (concurrency guard)
And session-token revocation runs early so any in-flight CLI calls with old tokens fail fast
And the token cache for the session is invalidated
And the lifecycle status is written to "closing"
And the session cache is invalidated after the write so subsequent auth misses read "closing"
And the host pane is terminated when a host pane reference is present and the session is not headless
And the resource-cleanup step runs (links, listeners, channel delete, workspace removal)
And the per-session tmpdir cleanup runs
And the inbound queue manager expires pending inbound messages for the session
And the escalation-end step clears relay state and emits `session.escalation_ended` if relay status was active
And the lifecycle write completes via close-session (or delete-session when the destructive variant is requested)
And the cache is invalidated one final time
And the session id is removed from the in-flight cleanup set
And the function reports success
```

#### Order of operations is fixed

```
Given the termination flow is mid-flight
Then the order is: revoke tokens -> lifecycle status = closing -> terminate host pane -> resource cleanup -> per-session tmpdir cleanup -> expire inbound -> end escalation -> close-session (or delete-session)
And every step after host-pane termination is wrapped in best-effort error handling
And a failure in any intermediate step is logged but does NOT prevent the final lifecycle write — once the host pane is gone, leaving the row stuck at "closing" would be worse than continuing
```

#### Concurrency guard

```
Given two parallel session-close-request events fire for the same session id
When both invoke terminate-session
Then the first call adds the session id to the in-flight cleanup set
And the second call sees the session id already present, logs a debug message, and returns immediately
And the in-flight set is cleared in a finalizer so a future retry can proceed
```

#### Missing session

```
Given the session id does not resolve to a session row
When terminate-session runs
Then the function logs at debug and returns without success
And no token revocation, host-pane termination, or cleanup is attempted
```

#### Already-closed session

```
Given the session row has a non-null closed-at marker
And the destructive delete variant is NOT requested (the default)
When terminate-session runs
Then the function records the already-closed state
And the lifecycle-status="closing" write is SKIPPED (the row stays at its closed status)
And the cleanup pass still runs (host-pane termination, resource cleanup, tmpdir, inbound expiry, escalation teardown) — straggling artifacts get reaped
And the final close-session call is also SKIPPED
And the function returns without reporting a new transition
```

#### Idempotency of resource cleanup

```
Given the resource-cleanup step is invoked twice for the same session
When the second call runs
Then link cleanup closes zero links (the first call already closed them)
And listener pop returns an empty list
And caller-listener cleanup is a no-op
And the adapter client's delete-channel may log a warning if the channel was already deleted but does not raise
And the workspace directory check short-circuits if the first call removed it
And no exception escapes the function
```

#### cleanup-stale-session — storage-active, host-pane-gone

```
Given a session row has lifecycle status reading as active
And the host pane named by the session no longer exists
And the session is older than 10 seconds (race-condition guard against just-created sessions)
And the session has a non-empty host-pane reference (headless sessions are skipped — they have no host pane to detect staleness against)
When the stale-session cleanup is called
Then a warning is logged: "Found stale session ... cleaning up"
And termination is invoked with reason "stale", host-pane termination suppressed (already gone), and the destructive delete variant requested (drop the row entirely)
And it reports success
```

#### cleanup-orphan-host-panes — host-pane-present, storage-absent

```
Given the host-pane layer is listing N host-pane sessions
When the orphan-host-pane sweep runs
Then the list is filtered to entries with the TeleClaude prefix, excluding the TUI host pane
And durable storage is queried for known host-pane references
And every TeleClaude-prefixed host pane not appearing in the known set is terminated
And the count of terminated host panes is returned
```

#### cleanup-orphan-workspaces — directory-present, storage-absent

```
Given the workspace base directory exists
When the orphan-workspace sweep runs
Then it iterates direct children, skipping symlinks and non-directories
And skips entries whose name is not a canonical UUID
And consults durable storage for known session ids
And recursively removes any UUID-named directory whose name is NOT in the known set
And returns the count of removed directories
```

#### cleanup-orphan-session-tmpdirs — per-session tmpdir sweep

```
Given the per-session tmpdir base directory exists and is a real directory (not a symlink)
When the orphan-tmpdir sweep runs
Then candidates iterate as direct children of the base dir
And entries that are symlinks or non-directories are skipped
And entries whose name is not a canonical UUID are skipped
And entries modified within the last 10 minutes (race-safety window) are skipped — guards against reaping a tmpdir for a just-spawned session
And entries whose name matches a live (non-closed) session id are skipped
And entries that resolve outside the configured base path are refused (symlink-escape guard)
And surviving entries are recursively removed
And the count of removed dirs is returned
```

#### cleanup-session-tmpdir — single session

```
Given a session id whose tmpdir path lives under the configured base
When the single-session tmpdir cleanup runs
Then the path is resolved via the safe-component helper (UUID or SHA-256 fallback)
And missing tmpdirs return without error
And symlink-or-not-a-dir paths are refused with a warning
And paths that do not resolve under the base are refused with a warning
And the removal swallows mid-walk "file vanished" errors (Node compile-cache vanish race) but propagates other exceptions
```

#### emit-recently-closed-session-events — restart-recovery sweep

```
Given the agent_runtime service restarted and some sessions closed before the restart left adapter-channel cleanup unfinished
When the recently-closed-session-events sweep runs (default window 60 seconds)
Then it enumerates closed sessions including headless ones
And keeps only entries whose closed-at marker is within the lookback window
And further keeps only entries that still carry a Telegram topic reference or Discord channel reference — the markers that channel deletion never completed
And emits a session-close-request event (NOT a session-closed event) for each so the subscriber path runs termination exactly once and clears the channel reference on success
And returns the count of emitted events
And a non-positive window short-circuits to zero emissions
```

### Cross-context references

- **session_mirrors** — consumer of the `session.ended` event family produced when the lifecycle write transitions to closed. Mirror extraction at session-end depends on the lifecycle write running, which is why the cleanup module guarantees the final close-session even when intermediate cleanup steps raise.
- **integration** — the escalation-end step clears relay status / Discord channel binding / relay-started-at on the session and emits `session.escalation_ended` (CLUSTER visibility) so the escalation integration can drop its corresponding Discord channel binding. The adapter-channel deletion side runs via the adapter client's delete-channel inside the resource-cleanup step.
- **identity** — token revocation runs early via session-token revocation plus token-cache invalidation. Downstream identity consumers see the token gone on the next cache miss.
- **workflow** — sessions spawned by orchestrators register one-shot stop-listeners on creation (see `session-lifecycle`); the resource-cleanup step removes both target-side and caller-side listener rows so notifications stop firing for the dead session.

## Known caveats

- **The lifecycle write at the end is non-negotiable.** Every intermediate step after host-pane termination is wrapped in best-effort error handling specifically so a single hiccup (e.g., a removal race on a per-session tmpdir) cannot strand a session at `lifecycle_status=closing`. If the lifecycle write were skipped on an inner failure, the session would be invisible to both the live UI and the close-reaper sweep.
- **Resource cleanup does NOT touch the lifecycle write.** Callers handle the lifecycle write; the resource-cleanup helper is purely for adapter / filesystem / listener teardown. The split exists so terminate-session and stale-session cleanup can both reuse the same resource sweep with different lifecycle intentions (close vs delete).
- **Headless sessions are excluded from stale detection.** They have no host-pane reference to consult, so stale detection short-circuits to false for them — they only ever close via explicit user/agent action.
- **Stale detection has a 10-second race-condition floor.** Sessions younger than 10 seconds are skipped to avoid reaping a just-created session whose host pane has not yet appeared.
- **Orphan-tmpdir sweep has a 10-minute race-safety window.** A tmpdir freshly created for a brand-new session is invisible to the sweep until its modification time ages past the window. The window is necessary because the row insert (which makes the session id "live") and the tmpdir creation are not co-transactional.
- **Symlink-escape guards on tmpdir removal.** Single-session and orphan-tmpdir sweeps both refuse to traverse symlinks and check that the resolved path remains under the configured base. A maliciously symlinked tmpdir cannot trick the sweep into removing arbitrary paths.
- **The recently-closed sweep re-emits a session-close request, not a session-closed event.** This is deliberate — it routes back through termination's idempotent path so the channel reference gets cleared on the second pass. Re-emitting a session-closed event would not run the channel-delete logic.
- **Orphan sweeps are time-bound to the maintenance tick (~1 hour).** There is no startup sweep that runs these unconditionally on boot — the first sweep happens immediately on periodic-cleanup entry (the first-run flag skips the initial sleep), but a freshly-rebooted service that crashes again within minutes can carry orphans across two restarts before they are observed.
- **The in-flight cleanup set is process-local.** Two service processes claiming the same session (which should not happen — there is one service per machine) would not coordinate through this guard. The guard exists to deduplicate parallel events within a single service, not to provide cross-process exclusion.
- **The destructive delete variant is, well, destructive.** It removes the row entirely rather than transitioning it to closed. The cleanup paths use this only for stale-session reaping, where the row carries no recoverable signal — preserving a tombstone for a session whose host pane died before the service noticed has no operational value.
