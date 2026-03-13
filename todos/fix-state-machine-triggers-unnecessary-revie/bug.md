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

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
