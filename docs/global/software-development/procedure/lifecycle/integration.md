---
id: 'software-development/procedure/lifecycle/integration'
type: 'procedure'
scope: 'domain'
description: 'Integration phase. Drive the integration state machine, handle squash commits, conflicts, push rejections, and lease contention.'
---

# Integration — Procedure

## Goal

Merge candidate branches to canonical main via the integration state machine, handling
each decision point until the queue is drained.

## Preconditions

- Candidate branches exist in the FIFO queue.
- No other integrator session holds the lease.
- The integrator operates in a persistent worktree at `trees/_integration/` (detached HEAD
  from `origin/main`), created on first run and reused across subsequent runs. Reset to
  `origin/main` before each merge. Repo root cleanliness is irrelevant — dirty files, hot
  patches, and operational edits on `main` do not affect integration.
- Worker worktrees branch from `origin/main` (not local HEAD).

## Steps

1. Call `telec todo integrate [slug]` to enter the state machine.
2. Read the returned instruction block and execute it verbatim.
3. After executing, call `telec todo integrate` again to advance.
4. Repeat until a terminal instruction is returned (COMPLETE or LEASE_BUSY).

The state machine returns one of the following instruction blocks at each step.

### SQUASH COMMIT REQUIRED

The branch has been squash-merged in the integration worktree (`trees/_integration/`);
staged changes are ready.

1. Read the context: diff stats, branch commit history, `requirements.md`,
   `implementation-plan.md`.
2. Compose a commit message capturing the full delivery intent:
   - Subject: imperative, scoped — e.g. `feat(my-feature): deliver my-feature`
   - Body: summarize what changed, key decisions, scope
   - Footer: `Co-Authored-By: TeleClaude <noreply@instrukt.ai>`
3. Run `git -C trees/_integration commit -m '<message>'`, then call `telec todo integrate`.

### CONFLICT RESOLUTION REQUIRED

The squash merge encountered conflicts in the integration worktree.

1. Read each conflicted file in `trees/_integration/`; understand the code on both sides.
2. Resolve all conflict markers (`<<<<`, `====`, `>>>>`).
3. Stage resolved files with `git -C trees/_integration add <files>`.
4. Compose a commit message (same quality standard as squash commit).
5. Run `git -C trees/_integration commit -m '<message>'`, then call `telec todo integrate`.
6. If conflicts are genuinely unresolvable, call `telec todo integrate` without
   committing — the state machine will detect this and re-prompt.

### PUSH REJECTION RECOVERY

Push from integration worktree to origin/main was rejected (likely non-fast-forward).

1. Diagnose: `git -C trees/_integration fetch origin && git -C trees/_integration log --oneline origin/main ^HEAD`.
2. Rebase: `git -C trees/_integration rebase origin/main`.
3. Resolve any new conflicts, then `git -C trees/_integration push origin HEAD:main`.
4. Call `telec todo integrate`.

### LEASE_BUSY

Another integrator session already holds the lease. Exit immediately.
Do not attempt to break the lease.

### ALREADY INTEGRATED (silent skip)

The state machine detected that the candidate's content is already on main —
either via git ancestry (regular merge) or via empty squash diff (squash merge
that produced no staged changes). The candidate is silently advanced to
`CANDIDATE_DELIVERED` and the next candidate is processed. No agent action needed.

This happens when a candidate is re-dequeued after a daemon restart or stale
re-queue. The agent sees no instruction for this candidate; the state machine
logs `integration.candidate.already_merged` and moves on.

### INTEGRATION COMPLETE

All candidates have been processed. Self-end: `telec sessions end self`.

## Outputs

- Merged candidates on canonical main (pushed from integration worktree).
- Delivery bookkeeping (roadmap delivered, demo snapshot promoted) on repo root.
- Cleaned worktrees and branches.
- `integration.*` lifecycle events at each state transition.

## Recovery

The state machine checkpoint is crash-safe. If the integrator process dies at any
point, re-calling `telec todo integrate` reads the durable checkpoint and resumes
from the last persisted phase. No manual checkpoint editing is required.

### Agent-actionable recovery

- **Squash commit fails:** Read the error and retry the commit in `trees/_integration/`.
- **Conflicts unresolvable:** Call `telec todo integrate` without committing — the state
  machine detects no HEAD advancement and re-prompts.
- **Push repeatedly rejected:** Fetch, rebase, resolve, push in `trees/_integration/`,
  then call `telec todo integrate`. If the problem persists, check for concurrent integrators.

### Automatic crash recovery

| Crash point                          | What happens on re-entry                                              |
| ------------------------------------ | --------------------------------------------------------------------- |
| After dequeue, before merge          | Resumes at merge. No work lost.                                       |
| After merge, before agent commits    | Re-prompts for commit. Git index (staged changes) persists on disk.   |
| After commit, before push            | Re-runs delivery bookkeeping (idempotent), then pushes.               |
| After push rejection                 | Re-checks if integration worktree HEAD matches remote main.           |
| During cleanup                       | Re-runs cleanup (idempotent). Missing worktrees/branches are no-ops.  |
| After candidate delivered            | Marks integrated, resets to IDLE, loops for next candidate.           |
