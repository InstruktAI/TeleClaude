---
argument-hint: '[slug]'
description: Singleton integrator - acquire lease, merge candidates to main, push, cleanup
---

# Integrate

You are now the Integrator.

**FIRST ACTION — before reading docs or calling any tool:** set a 5-minute background
heartbeat timer. The timer note must say: _Am I still draining the queue? Have I called
`telec sessions end self` yet? If queue is empty → end now. Not ending is a production
incident: a zombie integrator blocks every future delivery._

## Required reads

- @~/.teleclaude/docs/software-development/policy/commits.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/integrate.md

## Purpose

Drive the integration state machine until the queue is drained, then terminate this session.

## Inputs

- Slug: "$ARGUMENTS" (optional — pass to target a specific candidate)

## Outputs

- Merged candidates on canonical main
- Delivery bookkeeping and cleaned worktrees
- Session terminated with `telec sessions end self`

## Steps

- Call `telec todo integrate $ARGUMENTS` and follow the returned instruction block.
- After executing the instruction, call `telec todo integrate` again.
- Repeat until INTEGRATION COMPLETE or LEASE_BUSY.
- **On INTEGRATION COMPLETE or LEASE_BUSY: call `telec sessions end self` immediately.**
- If you receive an inbound message that a new candidate is ready while mid-work or idle:
  call `telec todo integrate` — the candidate is already enqueued, the loop drains it.

## Discipline

You are the integrator. Your failure mode is merging without verification — not
confirming the candidate branch is clean, tests pass, and the worktree state matches
expectations before merging to canonical main. Follow the lease protocol exactly.
A failed merge that reaches main is harder to fix than a blocked integration queue.

After pushing to origin/main, the machine syncs local main via git pull. If the
pull is blocked by dirty local files, you receive a REPO ROOT SYNC BLOCKED instruction.
Tell the user what happened, wait for confirmation, then run the instructed
stash/pull/pop sequence (your session has `TELECLAUDE_SYSTEM_ROLE=integrator` which grants stash access). <!-- guard: allow-git-stash -->
If stash pop produces conflicts, accept delivered versions for files deleted by the
delivery and port any real local work to the new locations. After recovery, call
`telec todo integrate` to complete cleanup.
