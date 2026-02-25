# Requirements - finalize-push-guardrails

## Problem

Worktree-scoped agents can currently advance `origin/main` directly (`git push origin main` or `gh pr merge`), bypassing canonical local `main`. This creates local/remote divergence and destabilizes the build-review-finalize pipeline.

## Goal

Enforce one invariant:

`origin/main` can only be advanced from canonical repository root on branch `main`, via orchestrator-controlled finalize apply.

## Scope

### In scope

- Split finalize into:
  - worker-owned `finalize-prepare` (worktree only, no merge/push),
  - orchestrator-owned `finalize-apply` (canonical `main` merge/push + roadmap/delivery updates).
- Add defense-in-depth guardrails for main-targeting operations:
  - `pre-push` hook checks for canonical context,
  - git wrapper push guard including `--no-verify` bypass prevention,
  - `gh pr merge` guard for base branch `main`.
- Ensure blocked attempts are auditable.
- Update finalize docs and command artifacts to the two-stage contract.

### Out of scope

- GitHub org/server-side branch protection settings.
- Credential model redesign (GitHub App or token partitioning).
- Separate finalize cleanup transaction/retry redesign.
- Preflight timeout redesign and general worktree convergence tuning.

## Canonical Context Contract

For any operation that can advance remote `main`, all checks must pass:

1. Repository top-level equals canonical path (`/Users/Morriz/Workspace/InstruktAI/TeleClaude`).
2. Current branch is `main`.
3. Operation source ref is `refs/heads/main`.
4. Repository is not a linked worktree (`git-dir == git-common-dir` for that process context).

## Functional Requirements

### R1. Finalize split is mandatory

- `next-finalize` run from `trees/{slug}` becomes prepare-only.
- Prepare stage must end with `FINALIZE_READY: {slug}` and stop.
- Prepare stage must not run merge/push against canonical main.

### R2. Apply is orchestrator-owned

- After `FINALIZE_READY`, orchestrator runs apply from project root (no worktree subfolder).
- Apply performs canonical `main` merge/push sequence and final bookkeeping.
- Delivery bookkeeping must use `todos/delivered.yaml` and `todos/roadmap.yaml`.

### R3. Main-targeting push guardrail

- Pushes targeting `refs/heads/main` from non-canonical context are rejected with explicit remediation text.
- Feature-branch pushes from worktrees remain allowed.

### R4. `--no-verify` cannot bypass main protection

- A push guard must still reject non-canonical main pushes when `git push --no-verify` is used.

### R5. `gh pr merge` guardrail

- `gh pr merge` with base branch `main` is rejected outside canonical context.
- Non-main PR merges are unaffected by this guardrail.

### R6. Auditability

- Rejected push/merge attempts must log enough context for incident tracing:
  - cwd,
  - branch,
  - target ref/base branch,
  - command,
  - session identifier (when available).

### R7. Existing lifecycle behavior remains intact

- Build/review/fix behavior remains unchanged.
- Only finalize behavior is split and hardened.

### R8. Installation and persistence

- Guardrail artifacts must be installed by allowed setup flow (`telec init`), not manual one-off steps.
- User interactive shell behavior must remain unaffected (agent-session PATH injection boundary preserved).

## Success Criteria

1. Worktree finalize cannot directly merge/push `main`.
2. Main-targeting push from worktree is blocked even with `--no-verify`.
3. `gh pr merge` to `main` is blocked from non-canonical context.
4. Orchestrator apply from canonical `main` is the only supported path to advance `origin/main`.
5. Delivery bookkeeping writes to `delivered.yaml` and roadmap removal remains correct.
6. No regression in feature-branch pushes from worktrees.
7. Guardrail rejections produce actionable logs.

## Verification Requirements

- Unit tests for next-machine finalize dispatch/post-completion behavior.
- Unit tests for push/merge guardrail logic (canonical vs non-canonical, main vs non-main).
- Regression check for roadmap/delivered bookkeeping path.
- `make test` and `make lint` pass.

## Dependencies and Preconditions

- Slug is active in `todos/roadmap.yaml`.
- No roadmap dependency prerequisites are declared for this slug.
- Canonical repo path and worktree layout remain unchanged during implementation.
- No new third-party dependencies are introduced.

## Risks

- Agents may retry blocked paths with alternate flags or tool forms.
- Dirty canonical `main` can still block apply if not handled explicitly.
- Partial rollout (docs without code, or one guardrail without others) can leave bypasses.
