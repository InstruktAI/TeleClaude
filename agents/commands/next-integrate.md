---
argument-hint: '[slug]'
description: Singleton integrator - acquire lease, merge candidates to main, push, cleanup
---

# Integrate

You are now the Integrator.

## Purpose

Drive the integration state machine by calling `telec todo integrate` in a loop,
executing the decision instructions returned at each step, then calling again until
the queue is empty or a terminal error is returned.

Only one integrator session may be active at a time. The lease mechanism enforces
this. If another integrator is running, the state machine returns a LEASE_BUSY
instruction — exit this session immediately.

## Inputs

- Slug: "$ARGUMENTS" (optional — pass to target a specific candidate; must match
  the next item in the FIFO queue, or omit to let the state machine pick)

## Outputs

- Merged candidates on canonical main
- Delivery bookkeeping (roadmap delivered, demo snapshot promoted)
- Cleaned worktrees and branches
- `integration.*` lifecycle events at each state transition
- Exit instruction when queue is drained

## Steps

Call `telec todo integrate $ARGUMENTS` and follow the instruction block verbatim.

**INTEGRATION DECISION: SQUASH COMMIT REQUIRED**

The branch has been squash-merged; staged changes are ready. Read the context:
diff stats, branch commit history, requirements.md, implementation-plan.md.
Compose a commit message capturing the full delivery intent:
- Subject: imperative, scoped — e.g. `feat(my-feature): deliver my-feature`
- Body: summarize what changed, key decisions, scope
- Footer: `Co-Authored-By: TeleClaude <noreply@instrukt.ai>`

Run `git commit -m '<your message>'`, then call `telec todo integrate`.

**INTEGRATION DECISION: CONFLICT RESOLUTION REQUIRED**

The squash merge encountered conflicts. Read each conflicted file; understand the
code on both sides. Resolve all conflict markers (`<<<<`, `====`, `>>>>`). Stage
resolved files with `git add <files>`. Compose a commit message (same quality
standard as squash commit). Run `git commit -m '<your message>'`, then call
`telec todo integrate`. If conflicts are genuinely unresolvable, call
`telec todo integrate` without committing — the state machine will detect this
and re-prompt.

**INTEGRATION DECISION: PUSH REJECTION RECOVERY**

Push of main to origin was rejected (likely non-fast-forward). Diagnose with
`git fetch origin && git log --oneline origin/main ^main`. Rebase:
`git rebase origin/main`. Resolve any new conflicts, then `git push origin main`,
then call `telec todo integrate`.

**INTEGRATION WAIT: Main branch not clear**

Another session is active or main has uncommitted changes. Wait for blockers to
clear, then call `telec todo integrate`.

**INTEGRATION ERROR: LEASE_BUSY**

Another integrator session already holds the lease. Exit this session immediately.
Do not attempt to break the lease.

**INTEGRATION COMPLETE: Queue empty**

All candidates have been processed. Self-end: `telec sessions end self`.

Repeat until INTEGRATION COMPLETE or LEASE_BUSY.
