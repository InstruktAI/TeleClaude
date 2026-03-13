# Bug: Integration state machine infinite loop on already-delivered squash merges. Ancestor check (merge-base --is-ancestor) is SHA-based and always fails for squash merges. Worktree reset on re-entry discards conflict resolutions. Affected: teleclaude/core/integration/state_machine.py (ancestor check ~L813, worktree reset ~L431, empty squash guard ~L834).

## Symptom

Integration state machine infinite loop on already-delivered squash merges. Ancestor check (merge-base --is-ancestor) is SHA-based and always fails for squash merges. Worktree reset on re-entry discards conflict resolutions. Affected: teleclaude/core/integration/state_machine.py (ancestor check ~L813, worktree reset ~L431, empty squash guard ~L834).

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-13

## Investigation

Traced the state machine execution path for already-delivered squash merge candidates:

1. `IntegrationQueue.__init__()` calls `_recover_in_progress_items()` on every instantiation,
   converting `in_progress` items back to `queued`.
2. For squash merges, `merge-base --is-ancestor` always fails (squash commits don't create
   ancestry links), so the ancestry guard in `_do_merge` and `_try_auto_enqueue` never fires.
3. The empty squash guard (`git diff --cached --quiet`) correctly detects the no-op and
   transitions to `CANDIDATE_DELIVERED`.
4. `CANDIDATE_DELIVERED` handler calls `queue.mark_integrated(key)`, but the item's status
   is `queued` (recovery changed it from `in_progress`).
5. `_ALLOWED_STATUS_TRANSITIONS` only allows `queued → in_progress`. The `queued → integrated`
   transition raises `IntegrationQueueError`, caught silently.
6. Item stays `queued`, state resets to IDLE, same item gets popped again — loops until
   `_LOOP_LIMIT` (50).

Secondary issues:
- `_try_auto_enqueue` only checks `status == "integrated"`, missing `in_progress`/`queued`.
- `_ensure_integration_worktree` does `git reset --hard origin/main` on every `_do_merge` call,
  discarding any active merge/conflict resolution state if `_do_merge` is re-entered.

## Root Cause

Queue state machine race: `_recover_in_progress_items()` transitions items to `queued` on every
`IntegrationQueue` instantiation, but `mark_integrated` only allows `in_progress → integrated`.
When recovery runs between pop and mark_integrated (across re-entry calls), the transition
`queued → integrated` is rejected, creating an infinite loop.

## Fix Applied

Three targeted changes:

1. **queue.py**: Added `"integrated"` to allowed transitions from `"queued"` in
   `_ALLOWED_STATUS_TRANSITIONS`. When recovery re-queues an in_progress item,
   `mark_integrated` now succeeds on the queued item.

2. **step_functions.py `_try_auto_enqueue`**: Changed guard from `status == "integrated"`
   to `existing is not None` — skips re-enqueue for any candidate already tracked in queue
   regardless of status.

3. **step_functions.py `_ensure_integration_worktree`**: Added active merge state detection
   (MERGE_HEAD or SQUASH_MSG exists) — skips `git reset --hard` when merge/conflict
   resolution is in progress, preserving agent work on re-entry.
