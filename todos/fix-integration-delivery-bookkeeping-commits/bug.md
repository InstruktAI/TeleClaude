# Bug: Integration delivery bookkeeping commits on repo root main diverge from origin/main. The delivery squash commit is pushed from trees/_integration/ worktree, but bookkeeping (roadmap deliver, todo cleanup) runs on repo root main. This creates a divergence requiring manual merge every time. Bookkeeping should either run in the integration worktree before push, or repo root should pull after the worktree push.

## Symptom

Integration delivery bookkeeping commits on repo root main diverge from origin/main. The delivery squash commit is pushed from trees/_integration/ worktree, but bookkeeping (roadmap deliver, todo cleanup) runs on repo root main. This creates a divergence requiring manual merge every time. Bookkeeping should either run in the integration worktree before push, or repo root should pull after the worktree push.

## Detail

<!-- No additional detail provided -->

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-13

## Investigation

Traced the integration delivery flow through the state machine in
`teleclaude/core/integration/step_functions.py`.

The integration state machine sequence was:
1. `_step_delivery_bookkeeping` — pushes squash merge commit from integration worktree (`trees/_integration/`) to `origin/main`
2. `_step_push_succeeded` — pulls `origin/main` to repo root, then commits bookkeeping (roadmap deliver, delivered.yaml) on repo root, transitions to cleanup
3. `_do_cleanup` — commits todo directory removal on repo root, pushes bookkeeping+cleanup commits from repo root to `origin/main`

The `pull --ff-only` at step 2 (line 587) fails when repo root has local commits not on `origin/main` (common in multi-agent environments where other agents commit to repo root). This failure is treated as non-fatal (logged as warning), so bookkeeping commits are created on a diverged repo root HEAD. The subsequent push from repo root at step 3 (line 674) also fails (non-fast-forward).

The next `telec todo integrate` call hits the entry-point pull at line 79 which is a hard error, blocking all future integration until manual merge.

## Root Cause

Bookkeeping operations (roadmap delivery, todo cleanup) were committed on repo root main and pushed separately from the squash merge commit which was pushed from the integration worktree. In multi-agent environments, repo root main can have local commits from other agents, causing `git pull --ff-only origin main` to fail. When this happens, bookkeeping commits diverge from `origin/main`, and the subsequent push from repo root also fails. This creates a persistent divergence that blocks future integration runs.

## Fix Applied

Moved all bookkeeping operations into the integration worktree so everything is pushed atomically in a single `git push origin HEAD:main`.

Changes in `teleclaude/core/integration/step_functions.py`:

1. **`_step_delivery_bookkeeping`**: Now runs `deliver_to_delivered()`, `git rm todos/{slug}`, and `clean_dependency_references()` in the integration worktree before pushing. All commits (squash + bookkeeping + cleanup) are pushed together.

2. **`_step_push_succeeded`**: Simplified to only sync repo root via `git pull --ff-only` (non-fatal if it fails since bookkeeping is already on origin/main). No more commits on repo root.

3. **`_do_cleanup`**: Reduced to physical cleanup only (worktree removal, branch deletion via `cleanup_delivered_slug`). No more git commits or pushes from repo root.
