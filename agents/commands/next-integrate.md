---
argument-hint: '[slug]'
description: Singleton integrator - acquire lease, merge candidates to main, push, cleanup
---

# Integrate

You are the singleton Integrator.

## Purpose

Acquire the integration lease, drain the READY candidate queue, merge each
candidate into canonical main, do delivery bookkeeping and cleanup, push
main, and self-end when done.

## Inputs

- Slug: "$ARGUMENTS" (the initial READY candidate that triggered this session)
- The integration queue may contain additional READY candidates

## Contract

Only one integrator session may be active at a time.  The lease mechanism
enforces this.  If another integrator is running, this session must exit
immediately.

## Steps

1. **Acquire lease:**
   ```bash
   # The lease is file-based at ~/.teleclaude/integration/lease.json
   # Use the IntegratorShadowRuntime with shadow_mode=False
   ```

2. **Drain the queue** (FIFO by ready_at):
   For each READY candidate in the queue:

   a. **Fetch and merge:**
      ```bash
      MAIN_REPO="$(git rev-parse --show-toplevel)"
      git -C "$MAIN_REPO" fetch origin main
      git -C "$MAIN_REPO" fetch origin <branch>
      git -C "$MAIN_REPO" switch main
      git -C "$MAIN_REPO" pull --ff-only origin main
      git -C "$MAIN_REPO" merge --squash <branch>
      TITLE="$(grep '^# ' "$MAIN_REPO/todos/<slug>/requirements.md" | head -1 | sed 's/^# //')"
      git -C "$MAIN_REPO" commit -m "feat(<slug>): ${TITLE:-deliver <slug>}"
      MERGE_COMMIT="$(git -C "$MAIN_REPO" rev-parse HEAD)"
      ```

   b. **If merge conflict:**
      - Emit `deployment.failed` event via bridge
      - Create follow-up todo (via BlockedFollowUpStore)
      - Mark queue item as blocked
      - Continue to next candidate

   c. **Delivery bookkeeping:**
      ```bash
      # If NOT a bug fix:
      telec roadmap deliver <slug> --commit "$MERGE_COMMIT"
      git -C "$MAIN_REPO" add todos/delivered.yaml todos/roadmap.yaml
      git -C "$MAIN_REPO" commit -m "chore(<slug>): record delivery"
      ```

   d. **Demo snapshot** (if demo.md exists):
      ```bash
      telec todo demo create <slug>
      ```

   e. **Cleanup:**
      ```bash
      git -C "$MAIN_REPO" worktree remove trees/<slug> --force
      git -C "$MAIN_REPO" branch -D <slug>
      rm -rf "$MAIN_REPO/todos/<slug>"
      git -C "$MAIN_REPO" add -A
      git -C "$MAIN_REPO" commit -m "chore: cleanup <slug>"
      ```

   f. **Push main:**
      ```bash
      git -C "$MAIN_REPO" push origin main
      ```

   g. **Emit deployment.completed** event via bridge

   h. **Restart daemon:**
      ```bash
      make restart
      ```

3. **When queue is empty:**
   - Release the integration lease
   - Write checkpoint
   - Self-end the session

## Outputs

- Merged candidates on canonical main
- Delivery bookkeeping (roadmap, delivered.yaml)
- Demo snapshots
- Cleaned up worktrees and branches
- deployment.completed events for each successful integration
- deployment.failed events for blocked candidates

## Error handling

- Merge conflicts: emit deployment.failed, create follow-up todo, continue
- Push failures: retry once, then emit deployment.failed
- Lease acquisition failure: exit immediately (another integrator is running)
