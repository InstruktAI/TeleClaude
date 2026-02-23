# DOR Report: deployment-auto-update

## Assessment Phase: Formal Gate

## Summary

Integration todo: wires version watcher signal + migration runner + daemon restart
into a single automated update flow. Phase 4 of 5 in `mature-deployment`. Depends
on `deployment-channels` (Phase 2) and `deployment-migrations` (Phase 3).

## Gate Results

| #   | Gate                         | Verdict              | Notes                                                                                                                                                              |
| --- | ---------------------------- | -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Intent & success             | PASS                 | Goal is clear: automated update on signal file detection. 9 success criteria are concrete and testable.                                                            |
| 2   | Scope & size                 | PASS                 | 1 new module + 1 daemon wiring + Redis status. Fits single session.                                                                                                |
| 3   | Verification                 | PASS                 | Unit tests for each path (alpha/beta, failure, signal removal). Integration test for full sequence. Edge case (ff-only failure) handled.                           |
| 4   | Approach known               | PASS (w/ tightening) | Pattern is clear: mirrors existing `deploy_service.py`. Two discrepancies fixed below.                                                                             |
| 5   | Research complete            | PASS                 | No new third-party deps. All reused patterns verified in codebase.                                                                                                 |
| 6   | Dependencies & preconditions | PASS (w/ note)       | Depends on `deployment-channels` (pending) and `deployment-migrations` (pending). Roadmap ordering is correct. Cannot build until both predecessors are delivered. |
| 7   | Integration safety           | PASS                 | New module, additive daemon task. Existing deploy flow unmodified. Rollback = revert commit + restart.                                                             |
| 8   | Tooling impact               | PASS                 | No scaffolding changes needed.                                                                                                                                     |

**Score: 8/10**

## Plan-to-Requirement Fidelity

| Requirement                                                | Plan Task                                               | Trace                |
| ---------------------------------------------------------- | ------------------------------------------------------- | -------------------- |
| Signal file triggers update sequence                       | Task 1.1 `check_for_update()` + Task 1.2 periodic check | OK                   |
| Alpha: `git pull --ff-only origin main`                    | Task 1.1 step 3                                         | OK                   |
| Beta/Stable: `git fetch --tags && git checkout v{version}` | Task 1.1 step 3                                         | OK                   |
| Migration runner executes for version gap                  | Task 1.1 step 4                                         | OK                   |
| `make install` runs after code update                      | Task 1.1 step 5                                         | OK                   |
| Daemon restarts via exit code 42                           | Task 1.1 step 8                                         | OK (tightened below) |
| Update status visible in Redis                             | Task 1.3                                                | OK                   |
| Migration failure halts update, no restart                 | Task 1.1 failure handling                               | OK                   |
| Signal file consumed after success                         | Task 1.1 step 6                                         | OK                   |

No contradictions. No orphan plan tasks. All 9 requirements trace to plan items.

## Codebase Verification

### Exit code 42 restart mechanism

- **Confirmed.** `teleclaude/services/deploy_service.py:128` uses `os._exit(42)`.
- **Discrepancy:** Plan says `sys.exit(42)`. Existing pattern uses `os._exit(42)` which
  bypasses cleanup handlers (intentional -- avoids race conditions during restart).
  Plan task 1.1 step 8 should use `os._exit(42)` to match.

### Redis status key pattern

- **Confirmed.** Key: `system_status:{computer_name}:deploy` used in:
  - `teleclaude/services/deploy_service.py:42` (write during deploy)
  - `teleclaude/core/lifecycle.py:110` (read on startup, transition "restarting" to "deployed")
- Plan task 1.3 correctly references this key pattern.

### Daemon background task registration

- **Confirmed.** Daemon registers background loops via `asyncio.create_task()` in
  `daemon.start()` (see hook_outbox, notification_outbox, todo_watcher, wal_checkpoint).
- **Tightening:** Plan task 1.2 says "Register periodic check (reuse cron interval or
  daemon background loop)". The cron system is a separate process and cannot trigger
  `os._exit(42)`. The update executor MUST run as an `asyncio.create_task()` background
  loop inside the daemon. The cron option is invalid and should be removed from the plan.

### Launchd KeepAlive

- **Confirmed.** `templates/ai.instrukt.teleclaude.daemon.plist` sets `KeepAlive: true`.
  Any exit (including code 42) triggers launchd to restart the daemon.

### Signal file path

- **Confirmed.** `~/.teleclaude/update_available.json` is consistent across
  deployment-channels and deployment-auto-update artifacts.

### Target module path

- **Confirmed.** `teleclaude/deployment/` does not exist yet. Will be created by
  deployment-channels (Phase 2) and deployment-migrations (Phase 3). No collision risk.

## Tightening Applied

1. **Plan task 1.1 step 8**: `sys.exit(42)` should be `os._exit(42)` to match
   existing `deploy_service.py` pattern (bypasses atexit handlers, avoids cleanup races).
2. **Plan task 1.2**: Removed ambiguity about "cron interval" -- update executor must
   be a daemon background task (`asyncio.create_task`), not a cron job.

## Open Questions Resolved

1. **`git pull --ff-only` vs `git fetch + reset`**: Resolved in requirements.md risk
   section. ff-only is the choice; failure skips the cycle. No decision needed.
2. **Updates during active sessions**: Resolved. Sessions survive daemon restart per
   architecture docs. Run immediately on signal.

## Actions Taken

- Verified exit code 42 pattern against `deploy_service.py` and launchd plist
- Verified Redis status key pattern against `deploy_service.py` and `lifecycle.py`
- Verified daemon background task registration patterns
- Confirmed `teleclaude/deployment/` directory does not yet exist (created by predecessors)
- Confirmed predecessor state: deployment-versioning (ready/score 9), deployment-channels (pending), deployment-migrations (pending)
- Identified and documented 2 tightening items (os.\_exit vs sys.exit, daemon task vs cron)
- Scored all 8 gates

## Blockers

None. Prerequisites are correctly sequenced in the roadmap. This todo cannot start
until deployment-channels and deployment-migrations are delivered, but the artifacts
themselves are ready for build once those land.
