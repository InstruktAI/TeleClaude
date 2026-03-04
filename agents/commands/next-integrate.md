---
argument-hint: '[slug]'
description: Singleton integrator - acquire lease, merge candidates to main, push, cleanup
---

# Integrate

You are now the Integrator.

## Purpose

Acquire the integration lease, drain the READY candidate queue, merge each
candidate into canonical main, do delivery bookkeeping and cleanup, push
main, and self-end when done.

Only one integrator session may be active at a time.  The lease mechanism
enforces this.  If another integrator is running, this session must exit
immediately.

## Inputs

- Slug: "$ARGUMENTS" (the initial READY candidate that triggered this session)
- The integration queue may contain additional READY candidates

## Outputs

- Merged candidates on canonical main
- Delivery bookkeeping (roadmap, delivered.yaml)
- Demo snapshots
- Cleaned up worktrees and branches
- deployment.completed events for each successful integration
- deployment.failed events for blocked candidates

## Steps

1. **Acquire lease:**
   The lease is file-based at `~/.teleclaude/integration/lease.json`.
   Use `IntegratorShadowRuntime` with `shadow_mode=False`.

2. **Drain the queue** (FIFO by ready_at):
   For each READY candidate in the queue:

   a. **Fetch and merge:**
      Fetch origin/main and origin/branch, switch to main, pull --ff-only,
      merge --squash the branch. Extract title from requirements.md for commit
      message.

   b. **If merge conflict:**
      - Emit `deployment.failed` event via bridge
      - Create follow-up todo (via BlockedFollowUpStore)
      - Mark queue item as blocked
      - Continue to next candidate

   c. **Delivery bookkeeping** (skip for bug fixes):
      Run `telec roadmap deliver <slug>`, stage delivery files, commit.

   d. **Demo snapshot** (if demo.md exists):
      Run `telec todo demo create <slug>`.

   e. **Cleanup:**
      Remove worktree, delete branch, remove todo directory, commit cleanup.

   f. **Push main:**
      Push origin main.

   g. **Emit deployment.completed** event via bridge.

   h. **Restart daemon** via `make restart`.

3. **When queue is empty:**
   - Release the integration lease
   - Write checkpoint
   - Self-end the session

4. **Error recovery:**
   - Merge conflicts: emit deployment.failed, create follow-up todo, continue
   - Push failures: retry once, then emit deployment.failed
   - Lease acquisition failure: exit immediately (another integrator is running)
