---
date: '2026-03-20'
description: 'Phantom git stash entries from test runs and stale worktree wrappers blocked the work state machine; resolved via test-isolation, worktree-preferring state IO, defense-in-depth autostash prevention, and a three-tier git permission model.'
number: '1'
visibility: 'public'
---

# ADR-0001: Git Stash Prevention in Multi-Worktree Environment — ADR

## Context

Phantom git stash entries kept appearing in the shared repo-wide stash, blocking the work state machine's stash-debt precondition across all worktrees. The root cause was a permission test that ran a real `git stash` against the shared repo, compounded by worktrees resolving a stale, frozen copy of the git wrapper with different permission rules. Autostash on rebase/merge was a second latent source.

## Decision

Prevent shared-stash pollution through layered, defense-in-depth measures plus a permission model:

- **Test isolation.** Any test exercising git operations runs against a temp repo, never the shared one.
- **Autostash disabled everywhere.** Both the git wrapper and the GitPython paths force autostash off; merges commit pending changes rather than stashing.
- **Worktree-preferring state IO.** Lifecycle state reads/writes route to the worktree when one exists, and the work phase commits its state atomically, preventing drift between main and worktree.
- **A three-tier git permission model.** Destructive operations (restore, clean, switch, reset, revert) are blocked for all roles; protected operations (stash, commit/push on main) are integrator-only; an orchestrator cannot commit on any branch.
- **A stash watchdog and wrapper logging** as the detection surface for any regression.

## Consequences

- Load-bearing invariants: no test creates git state in the shared repo; state writes prefer worktrees; autostash is off on every path; the wrapper is used via its canonical (non-stale) copy.
- Cost: defense-in-depth means several code paths enforce autostash-off, which future git-touching code must maintain; the three-tier model is operational friction for legitimate integrator stash needs.
- A regression in any invariant surfaces through the watchdog and the wrapper log rather than silently.
