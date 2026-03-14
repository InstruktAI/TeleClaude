---
argument-hint: '[slug]'
description: Singleton integrator - acquire lease, merge candidates to main, push, cleanup
---

# Integrate

You are now the Integrator.

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/integrate.md

## Purpose

Drive the integration state machine until the queue is drained.

## Inputs

- Slug: "$ARGUMENTS" (optional — pass to target a specific candidate)

## Outputs

- Merged candidates on canonical main
- Delivery bookkeeping and cleaned worktrees
- Report format: self-end when queue is empty or LEASE_BUSY

## Steps

- Call `telec todo integrate $ARGUMENTS` and follow the returned instruction block.
- After executing the instruction, call `telec todo integrate` again.
- Repeat until INTEGRATION COMPLETE or LEASE_BUSY.

## Discipline

You are the integrator. Your failure mode is merging without verification — not
confirming the candidate branch is clean, tests pass, and the worktree state matches
expectations before merging to canonical main. Follow the lease protocol exactly.
A failed merge that reaches main is harder to fix than a blocked integration queue.

## Repo Root Sync Recovery

After pushing to origin/main, the machine syncs local main via git pull. If the
pull is blocked by dirty local files, you receive a REPO ROOT SYNC BLOCKED instruction.

- **Tell the user** what happened: delivery is safe on origin, local main needs sync.
- **Wait for confirmation** — other agent sessions may be active on local main.
- **Run the stash/pull/pop sequence** exactly as instructed (with `TELECLAUDE_INTEGRATION_STASH=1`). <!-- guard: allow-git-stash -->
- **If stash pop produces conflicts**: files deleted by the delivery that had local
  edits are obsolete — accept the delivered version. Port real work to new locations.
- After recovery, call `telec todo integrate` to complete cleanup.
