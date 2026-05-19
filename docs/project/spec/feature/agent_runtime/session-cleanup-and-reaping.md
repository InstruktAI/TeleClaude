---
id: 'project/spec/feature/agent_runtime/session-cleanup-and-reaping'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'v1 agent_runtime — terminate a session, free its tmux + workspace + tmpdir resources, sweep orphans, and replay close-requested events for sessions whose channel cleanup never completed.'
---

# Session Cleanup and Reaping — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The cleanup half of v1 agent_runtime session lifecycle. Where `session-lifecycle` accepts a close request, this surface performs it: token revocation, tmux kill, conversation-link teardown, listener cleanup, adapter channel deletion, workspace `rmtree`, per-session TMPDIR removal, escalation teardown, inbound expiry, and the final `closing -> closed` lifecycle write.

It also reconciles the gap between what the DB believes and what the system holds: stale sessions (DB-active but tmux-gone), orphan tmux sessions (`tc_`-prefixed tmux session with no DB row), orphan workspace directories (UUID-named directory under the workspace base with no DB row), and orphan per-session TMPDIRs (UUID-named subdirectory under the configured tmpdir base, not bound to a live session).

Finally, it provides the recently-closed replay mechanism: an `emit_recently_closed_session_events` sweep that re-emits `SESSION_CLOSE_REQUESTED` for closed sessions whose adapter channel reference (`telegram.topic_id` / `discord.channel_id`) is still set — recovering channel-deletion work that was dropped across a daemon restart.

The cleanup loop runs on the maintenance service tick (every hour by default). `DELETE /sessions/{id}` reaches `terminate_session` synchronously via the command service.

## Canonical fields

### Behavioral contract

#### terminate_session — happy path

```
Given a non-closed Session row exists for session_id
And the caller invokes `terminate_session(session_id, adapter_client, reason=...)`
When the cleanup begins
Then session_id is added to `_cleanup_in_flight` (a module-level set, concurrency guard)
And `db.revoke_session_tokens(session_id)` runs early so any in-flight CLI calls with old tokens fail fast
And `invalidate_token_cache(session_id)` is called
And lifecycle_status is written to `"closing"`
And `invalidate_session_cache(session_id)` runs after the write so subsequent auth misses read `closing`
And tmux is killed via `tmux_bridge.kill_session(session.tmux_session_name)` when a tmux name is present and the session is not headless
And `cleanup_session_resources` runs (links, listeners, channel delete, workspace rmtree)
And `cleanup_session_tmpdir` runs (per-session TMPDIR rmtree)
And `get_inbound_queue_manager().expire_session(session_id)` expires pending inbound messages
And `_end_escalation_if_active` clears relay state and emits `session.escalation_ended` if relay_status was `active`
And the lifecycle write completes via `db.close_session(session_id)` (or `db.delete_session` when `delete_db=True`)
And the cache is invalidated one final time
And session_id is removed from `_cleanup_in_flight`
And the function returns True
```

#### Order of operations is fixed

```
Given terminate_session is mid-flight
Then the order is: revoke tokens -> lifecycle_status=closing -> kill tmux -> cleanup_session_resources -> cleanup_session_tmpdir -> expire inbound -> end escalation -> db.close_session (or delete_session)
And every step after the tmux kill is wrapped in best-effort try/except
And a failure in any intermediate step is logged but does NOT prevent the final lifecycle write — once tmux is gone, leaving the row stuck at `closing` would be worse than continuing
```

#### Concurrency guard

```
Given two parallel SESSION_CLOSE_REQUESTED events fire for the same session_id
When both invoke terminate_session
Then the first call adds session_id to `_cleanup_in_flight`
And the second call sees session_id already present, logs a debug message, and returns False immediately
And the in-flight set is cleared in a finally block so a future retry can proceed
```

#### Missing session

```
Given session_id does not resolve to a Session row
When terminate_session runs
Then the function logs at debug and returns False
And no token revocation, tmux kill, or cleanup is attempted
```

#### Already-closed session

```
Given the Session row has a non-null closed_at
And `delete_db=False` (the default)
When terminate_session runs
Then `already_closed=True` is recorded
And the lifecycle_status=closing write is SKIPPED (the row stays at its closed status)
And the cleanup pass still runs (tmux kill, resource cleanup, tmpdir, inbound expiry, escalation teardown) — straggling artifacts get reaped
And `db.close_session` at the end is also SKIPPED
And the function returns False (no new transition happened)
```

#### Idempotency of cleanup_session_resources

```
Given cleanup_session_resources is invoked twice for the same Session
When the second call runs
Then cleanup_session_links closes zero links (the first call already closed them)
And pop_listeners returns an empty list
And cleanup_caller_listeners is a no-op
And adapter_client.delete_channel may log a warning if the channel was already deleted but does not raise
And the workspace directory check via `workspace_dir.exists()` short-circuits if the first call removed it
And no exception escapes the function
```

#### cleanup_stale_session — DB-active, tmux-gone

```
Given a Session row has lifecycle_status reading as active
And the tmux session named by `session.tmux_session_name` no longer exists
And the session is older than 10 seconds (race-condition guard against just-created sessions)
And the session has a non-empty tmux_session_name (headless sessions are skipped — they have no tmux to detect staleness against)
When cleanup_stale_session is called
Then a warning is logged: "Found stale session ... cleaning up"
And terminate_session is invoked with `reason="stale"`, `kill_tmux=False` (tmux already gone), and `delete_db=True` (drop the row entirely)
And returns True
```

#### cleanup_orphan_tmux_sessions — tmux-present, DB-absent

```
Given the tmux server is listing N tmux sessions
When cleanup_orphan_tmux_sessions runs
Then the list is filtered to entries with the `tc_` prefix (TeleClaude-owned), excluding `tc_tui` (the TUI wrapper)
And the DB is queried via `db.get_all_sessions()` for known tmux_session_names
And every `tc_`-prefixed tmux session not appearing in the known set is killed via `tmux_bridge.kill_session`
And the count of killed sessions is returned
```

#### cleanup_orphan_workspaces — directory-present, DB-absent

```
Given the workspace base directory `OUTPUT_DIR` exists
When cleanup_orphan_workspaces runs
Then it iterates direct children, skipping symlinks and non-directories
And skips entries whose name is not a canonical UUID (via `_is_uuid_name`)
And consults `db.get_all_sessions()` for known session_ids
And shutil.rmtree-s any UUID-named directory whose name is NOT in the known set
And returns the count of removed directories
```

#### cleanup_orphan_session_tmpdirs — per-session TMPDIR sweep

```
Given the per-session TMPDIR base directory exists and is a real directory (not a symlink)
When cleanup_orphan_session_tmpdirs runs
Then candidates iterate as direct children of the base dir
And entries that are symlinks or non-directories are skipped
And entries whose name is not a canonical UUID are skipped
And entries modified within the last `SESSION_TMPDIR_RACE_SAFETY` window (10 minutes by default) are skipped — guards against reaping a tmpdir for a just-spawned session
And entries whose name matches a live (non-closed) session_id are skipped
And entries that resolve outside the configured base path are refused (symlink-escape guard)
And surviving entries are shutil.rmtree-d
And the count of removed dirs is returned
```

#### cleanup_session_tmpdir — single session

```
Given a session_id whose tmpdir path lives under the configured base
When cleanup_session_tmpdir runs
Then the path is resolved via `safe_session_tmp_component` (UUID or SHA-256 fallback)
And missing tmpdirs return False (no error)
And symlink-or-not-a-dir paths are refused with a warning
And paths that do not resolve under the base are refused with a warning
And `_rmtree_ignore_vanished` swallows mid-walk `FileNotFoundError` (Node compile-cache vanish race) but propagates other exceptions
```

#### emit_recently_closed_session_events — restart-recovery sweep

```
Given the daemon restarted and some sessions closed before the restart left adapter-channel cleanup unfinished
When emit_recently_closed_session_events runs (default `seconds=60`)
Then it enumerates closed sessions with `include_headless=True`
And keeps only entries whose `closed_at` is within the lookback window (now - 60s by default)
And further keeps only entries that still carry a `telegram.topic_id` or `discord.channel_id` — the markers that channel deletion never completed
And emits `SESSION_CLOSE_REQUESTED` (NOT `SESSION_CLOSED`) for each so the subscriber path runs terminate_session exactly once and clears the channel reference on success
And returns the count of emitted events
And `seconds <= 0` short-circuits to 0 emissions
```

### Implementation pointers (v1)

- `teleclaude/core/session_cleanup.py`
  - Constants: `TMUX_SESSION_PREFIX = "tc_"` (line 40), `TMUX_TUI_SESSION_NAME = "tc_tui"` (line 41), `RECENTLY_CLOSED_SESSION_SECONDS = 60` (line 46), `SESSION_TMPDIR_RACE_SAFETY = timedelta(minutes=10)` (line 47), `_cleanup_in_flight: set[str]` (line 51)
  - `cleanup_session_tmpdir` (line 86) — single-session TMPDIR delete with safety guards
  - `cleanup_orphan_session_tmpdirs` (line 103) — orphan tmpdir sweep with race-safety window
  - `cleanup_session_resources` (line 146) — links + listeners + channel + workspace
  - `_end_escalation_if_active` (line 201) — escalation_ended emission, clears relay state
  - `terminate_session` (line 219) — public entry, concurrency guard
  - `_terminate_session_inner` (line 260) — actual cleanup sequence
  - `emit_recently_closed_session_events` (line 372) — restart-recovery replay
  - `cleanup_stale_session` (line 432) — DB-active, tmux-gone single-session reaper
  - `cleanup_all_stale_sessions` (line 477) — sweep wrapper over all active sessions
  - `cleanup_orphan_tmux_sessions` (line 506) — tmux-present, DB-absent reaper
  - `cleanup_orphan_workspaces` (line 551) — directory-present, DB-absent reaper
- `teleclaude/services/maintenance_service.py` — `periodic_cleanup` (line 53) wires the sweeps into the daemon's hourly maintenance loop:
  - `emit_recently_closed_session_events` (line 63)
  - `cleanup_orphan_tmux_sessions` (line 64)
  - `cleanup_orphan_workspaces` (line 65)
  - `cleanup_orphan_session_tmpdirs` (line 66)
- `teleclaude/api/sessions_routes.py` — `end_session` (line 596) dispatches `CloseSessionCommand` via the command service, which ultimately reaches `terminate_session`.
- CLI surface: `telec sessions end <id>` → `DELETE /sessions/{id}` → `CloseSessionCommand` → `terminate_session`.

### Cross-context references

- **session_mirrors** — consumer of the `session.ended` event family produced when the lifecycle write transitions to `closed`. Mirror extraction at session-end depends on the lifecycle write running, which is why the cleanup module guarantees the final `db.close_session` even when intermediate cleanup steps raise.
- **integration** — `_end_escalation_if_active` clears `relay_status` / `relay_discord_channel_id` / `relay_started_at` on the Session and emits `session.escalation_ended` (CLUSTER visibility) so the escalation integration can drop its corresponding Discord channel binding. The adapter-channel deletion side runs via `adapter_client.delete_channel(session)` inside `cleanup_session_resources`.
- **identity** — token revocation runs early via `db.revoke_session_tokens(session_id)` + `invalidate_token_cache(session_id)`. Downstream identity consumers see the token gone on the next cache miss.
- **workflow** — sessions spawned by orchestrators register one-shot stop-listeners on creation (`session-lifecycle`); `cleanup_session_resources` invokes `pop_listeners(session_id)` (target side) and `cleanup_caller_listeners(session_id)` (caller side) so notifications stop firing for the dead session.

## Known caveats

- **The lifecycle write at the end is non-negotiable.** Every intermediate step after the tmux kill is wrapped in best-effort try/except specifically so a single hiccup (e.g., an `rmtree` race on a per-session tmpdir) cannot strand a session at `lifecycle_status=closing`. If the lifecycle write were skipped on an inner failure, the session would be invisible to both the live UI and the close-reaper sweep.
- **`cleanup_session_resources` does NOT touch the DB.** Callers handle the lifecycle write; this helper is purely for adapter / filesystem / listener teardown. The split exists so `terminate_session` and `cleanup_stale_session` can both reuse the same resource sweep with different DB intentions (close vs delete).
- **Headless sessions are excluded from stale detection.** They have no tmux name to consult, so `cleanup_stale_session` short-circuits to False for them — they only ever close via explicit user/agent action.
- **Stale detection has a 10-second race-condition floor.** Sessions younger than 10 seconds are skipped to avoid reaping a just-created session whose tmux pane has not yet appeared.
- **Orphan-tmpdir sweep has a 10-minute race-safety window** — `SESSION_TMPDIR_RACE_SAFETY`. A tmpdir freshly created for a brand-new session is invisible to the sweep until its mtime ages past the window. The window is necessary because the DB row insert (which makes the session_id "live") and the tmpdir creation are not co-transactional.
- **Symlink-escape guards on tmpdir removal.** `cleanup_session_tmpdir` and `cleanup_orphan_session_tmpdirs` both refuse to traverse symlinks and check that the resolved path remains under the configured base. A maliciously symlinked tmpdir cannot trick the sweep into removing arbitrary paths.
- **`emit_recently_closed_session_events` re-emits `SESSION_CLOSE_REQUESTED`, not `SESSION_CLOSED`.** This is deliberate — it routes back through `terminate_session`'s idempotent path so the channel reference gets cleared on the second pass. Re-emitting `SESSION_CLOSED` would not run the channel-delete logic.
- **Orphan sweeps are time-bound to the maintenance tick (~1 hour).** There is no daemon-startup sweep that runs these unconditionally on boot — first sweep happens immediately on `periodic_cleanup` entry (the `first_run` flag skips the initial sleep), but a freshly-rebooted daemon that crashes again within minutes can carry orphans across two restarts before they are observed.
- **The `_cleanup_in_flight` set is process-local.** Two daemon processes claiming the same session (which should not happen — there is one daemon per machine) would not coordinate through this guard. The guard exists to deduplicate parallel events within a single daemon, not to provide cross-process exclusion.
- **`delete_db=True` is a destructive variant.** It calls `db.delete_session` instead of `db.close_session`, removing the row entirely rather than transitioning it to `closed`. v1 uses this only for stale-session reaping (`cleanup_stale_session`), where the row carries no recoverable signal — preserving a tombstone for a session whose tmux died before the daemon noticed has no operational value.
- **v2-target framings deliberately not covered here:** `commit-then-emit` event posture, `agent_runtime.session.ended` payload with `native_file_path`, the LISTEN/NOTIFY trigger model, `SessionRuntime` actor teardown — those describe v2 shape; v1 emits adapter-channel and lifecycle events through the existing event_bus + adapter paths during the cleanup sequence above.
