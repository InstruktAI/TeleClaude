# Bug: State machine triggers unnecessary review round after finalize merges main into worktree. The finalize step commits a merge-main commit, which causes the state machine to dispatch a round 2 review on those integration commits. Post-finalize merge commits are not new code — they should not trigger a review cycle. The fix should add a review_before_finalize_sha checkpoint so the state machine only reviews commits up to the finalize boundary, not the merge commit itself.

## Symptom

State machine triggers unnecessary review round after finalize merges main into worktree. The finalize step commits a merge-main commit, which causes the state machine to dispatch a round 2 review on those integration commits. Post-finalize merge commits are not new code — they should not trigger a review cycle. The fix should add a review_before_finalize_sha checkpoint so the state machine only reviews commits up to the finalize boundary, not the merge commit itself.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-13

## Investigation

The stale review approval guard in `next_work()` (`core.py:4398-4421`) compares
`review_baseline_commit` (set at review approval time) against current worktree HEAD.
When HEAD differs and `_has_meaningful_diff()` finds non-infrastructure files changed
by non-merge commits in the range, it resets review to PENDING.

The finalize worker merges `origin/main` into the worktree (`git merge origin/main
--no-edit`), creating a merge commit. While `_has_meaningful_diff()` uses `--no-merges`
to filter the merge commit itself, the regular commits from main brought into the
`baseline..head` range ARE included — and they touch meaningful production files.

The stale check ran BEFORE `finalize_state` was read, so it had no way to know that
finalize was already in progress. It would invalidate the review, reset to PENDING,
and the subsequent finalize handoff checks at lines 4429/4437 never executed because
`review_status` was no longer APPROVED.

## Root Cause

Ordering bug: `finalize_state` was read at line 4423, after the stale review check at
lines 4398-4421. The stale check had no visibility into finalize status and incorrectly
invalidated review approval when the only new commits were from the finalize merge-main
step. Commits from `origin/main` brought in by the merge are not merge commits — they
pass through the `--no-merges` filter in `_has_meaningful_diff()`.

## Fix Applied

Moved `finalize_state = _get_finalize_state(state)` before the stale review guard.
Added `finalize_status` check: when finalize is `ready` or `handed_off`, skip the
stale review check entirely. Post-finalize merge-main commits are infrastructure,
not new code requiring re-review. The finalize was dispatched because review was
already approved — re-validating against merge artifacts is incorrect.
