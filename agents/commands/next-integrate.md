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
