# Input: finalize-push-guardrails

## Problem Statement

AI agents in worktrees can advance `origin/main` directly — either via `git push origin main` or `gh pr merge` — bypassing the canonical local `main` checkout. This is the primary root cause of cascading regressions in the build/review/finalize lifecycle.

## Evidence

### Direct observation

- Finalize/push executed from an alternate worktree context advanced `origin/main` while canonical local `main` stayed behind and dirty.
- Subsequent worktree prep/sync branched from stale local state and produced cascading conflicts and misrouting.

### Architectural leak in `next-finalize`

- `next_work` dispatches `/next-finalize` with `subfolder="trees/{slug}"` (worktree context).
- The finalize procedure (`docs/software-development/procedure/lifecycle/finalize.md`, steps 5-6) instructs the worker to reach back into canonical main via `git -C "$MAIN_REPO"`:
  ```bash
  git -C "$MAIN_REPO" switch main
  git -C "$MAIN_REPO" pull --ff-only origin main
  git -C "$MAIN_REPO" merge {slug} --no-edit
  git -C "$MAIN_REPO" push origin main
  ```
- When dirty state on local `main` blocks `pull --ff-only` or `switch`, the agent improvises alternative paths — this is where regressions originate.

### Missing guardrails

- The git wrapper (`~/.teleclaude/bin/git`) blocks `stash`, `checkout`, `restore`, `clean`, `reset --hard`, but does NOT block `push` to main from non-canonical contexts.
- No `pre-push` hook exists (`.githooks/` directory is absent).
- No wrapper exists for `gh pr merge` — agents can merge PRs to main from any context.

## Root Cause Analysis

### Primary root cause (this todo)

Push-bypass: worktree agents advancing remote main without going through local main. Creates divergence between local and remote, stale worktree bases, and conflict cascades.

### Secondary causes (partially downstream, partially independent)

- **State/artifact divergence:** Bidirectional copying of `state.yaml` and todo artifacts between `trees/{slug}/todos/` and `todos/` drifts independently of push-bypass. One-way bootstrap + checkpoint promotion model needed.
- **Cleanup incompletion:** Non-transactional finalize post-steps, policy-blocked cleanup commands, missing retry/recovery. Gets worse when finalize runs from wrong context but is its own bug class.
- **Preflight timeouts:** Long-running worktree convergence causing transport timeouts and state-machine retries.

## Discussion Record

This analysis was produced through a direct peer-to-peer agent conversation (sessions `4d88b839` and `b5950c30`) with Mo observing and providing direction. Both agents converged independently on the same root cause and fix strategy.
