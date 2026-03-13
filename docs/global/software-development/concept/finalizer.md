---
description: 'Post-review prepare role. Merge origin/main into the worktree branch, push it, and report FINALIZE_READY.'
id: 'software-development/concept/finalizer'
scope: 'domain'
type: 'concept'
---

# Finalizer — Concept

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/overview.md

## What

Post-review prepare role. Run finalize prepare in the worktree, publish the candidate branch, and hand off durable readiness to the orchestrator.

1. **Verify approval** - Only finalize after explicit APPROVE verdict.
2. **Finalize prepare** - Integrate `origin/main` in the worktree branch.
3. **Publish candidate** - Push the finalized feature/worktree branch to `origin/<slug>`.
4. **Report readiness** - Emit `FINALIZE_READY`; the orchestrator records durable finalize state.
5. **Handoff only** - Integration, delivery bookkeeping, and cleanup are handled downstream by the integration event chain.

## Why

This keeps the finalizer narrowly scoped to branch preparation, leaves canonical `main` ownership with the integrator, and makes the handoff durable before cleanup begins.
