# Review Findings: fix-integration-delivery-bookkeeping-commits

**Review round:** 1
**Commit reviewed:** 300d8a354 (fix(integration): run delivery bookkeeping in integration worktree to prevent repo root divergence)
**Files changed:** `teleclaude/core/integration/step_functions.py`

## Fix Assessment

The fix correctly identifies and addresses the root cause: bookkeeping commits (roadmap delivery, todo cleanup) were created on repo root main and pushed separately from the squash merge commit, causing divergence when repo root had local commits from other agents.

The solution moves all bookkeeping into the integration worktree so everything pushes atomically via a single `git push origin HEAD:main`. The approach is sound:

- `_step_delivery_bookkeeping` now runs `deliver_to_delivered`, `git rm todos/{slug}`, and `clean_dependency_references` in the integration worktree before pushing
- `_step_push_succeeded` is simplified to repo root sync only (non-fatal if it fails)
- `_do_cleanup` is reduced to physical artifact cleanup via `cleanup_delivered_slug`

## Critical

### C1: No reproduction test for bug fix

**Location:** tests/ (missing)
**Policy:** Testing policy requires a reproduction test for every bug fix. "Every bug fix starts with a test that reproduces the bug (RED). The reproduction test becomes a permanent regression guard."

No test file exists for `step_functions.py`. No test was added or modified in this change. The bug — bookkeeping commits diverging from origin/main when repo root has local commits — needs a test that proves the old behavior was broken and the new behavior is correct.

**Remediation:** Add a test that:
1. Sets up an integration worktree scenario with a squash merge commit
2. Simulates repo root having local commits (non-fast-forwardable)
3. Verifies that bookkeeping (roadmap delivery, todo removal) is committed in the integration worktree and pushed atomically with the squash merge
4. Verifies that repo root pull failure is non-fatal

### C2: Missing demo artifact

**Location:** `todos/fix-integration-delivery-bookkeeping-commits/demo.md` (missing)
**Policy:** Demo artifact review requires either executable bash blocks or a valid `<!-- no-demo: reason -->` marker.

This is a pure internal refactor with zero user-visible behavior change (integration state machine internals). A `<!-- no-demo: ... -->` marker is valid here, but the file must exist.

**Remediation:** Create `demo.md` with `<!-- no-demo: pure internal refactor — integration state machine bookkeeping moved between worktrees, no CLI/config/API changes -->`.

## Important

None.

## Suggestions

### S1: `_is_bug_slug` uses repo root instead of integration worktree

**Location:** `step_functions.py:535`

All bookkeeping now runs in the integration worktree, but `_is_bug_slug(cwd, key.slug)` checks `Path(cwd) / "todos" / slug / "bug.md"` on repo root. Should use `wt` for consistency since the bookkeeping context is the worktree. Functionally equivalent because `bug.md` exists in both locations (scaffolded on main), but conceptually inconsistent.

### S2: Redundant `clean_dependency_references` call

**Location:** `step_functions.py:564` and `delivery.py:187`

`clean_dependency_references` is called twice: once directly in the integration worktree (line 564) and again on repo root via `cleanup_delivered_slug` (delivery.py:187). The second call is harmless due to idempotency but creates confusion about the separation of concerns between "git-tracked bookkeeping in worktree" and "physical cleanup on repo root."

## Resolved During Review

### R1: `_do_cleanup` docstring inaccuracy (was Important)

**Location:** `step_functions.py:676`
**Action:** Fixed docstring. The original claimed "only physical artifacts" but `cleanup_delivered_slug` also runs `clean_dependency_references` (a data operation). Updated to accurately describe what the delegate function does.

## Fixes Applied

### C1 — Reproduction test added
**Commit:** d7f665b97
**File:** `tests/unit/core/integration/test_step_delivery_bookkeeping.py`
Two tests:
1. `test_bookkeeping_runs_in_integration_worktree_not_repo_root` — verifies `deliver_to_delivered` and `clean_dependency_references` are called with the integration worktree path, all git ops (commit/push) target the worktree, and push uses `HEAD:main` atomically.
2. `test_repo_root_pull_failure_is_nonfatal` — simulates `pull --ff-only` failing on repo root and verifies the step continues to CANDIDATE_DELIVERED.

### C2 — demo.md created
**Commit:** d7f665b97
**File:** `todos/fix-integration-delivery-bookkeeping-commits/demo.md`
Added `<!-- no-demo: pure internal refactor — integration state machine bookkeeping moved between worktrees, no CLI/config/API changes -->`.

## Verdict

**APPROVE**

Unresolved Critical: 0
Unresolved Important: 0
Suggestions: 2 (S1, S2 — not addressed; suggestions only)
