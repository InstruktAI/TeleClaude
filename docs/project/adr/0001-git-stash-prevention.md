---
id: 'project/adr/0001-git-stash-prevention'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '1'
date: '2026-03-20'
adr_status: 'accepted'
description: 'Phantom git stash entries from test runs and stale worktree wrappers blocked the work state machine; resolved via test-isolation, mark-phase auto-commit, worktree-preferring state IO, and defense-in-depth autostash prevention.'
---

# ADR-0001: Git Stash Prevention in Multi-Worktree Environment — ADR

## Context

Phantom git stash entries kept appearing in the shared repository stash, blocking the work state machine's stash-debt precondition check. Multiple agents across multiple worktrees were affected. The stash is repo-wide — an entry created in one worktree blocks all worktrees.

Root cause: `tests/unit/install/test_git_wrapper_permissions.py` ran `git stash` through the wrapper to test permission enforcement. The `test_integrator_allowed` test used `role="integrator"` which allows stash — and created a REAL stash entry in the shared repo-wide stash. No `cwd` was set, so the stash landed in the project repository.

When `run_build_gates` ran `make test` in a worktree, the test suite resolved the wrapper from `Path(__file__).parents[3]` — which in a worktree pointed to the worktree's stale copy of the wrapper (frozen at worktree creation time). This old wrapper had different permission rules, compounding the problem.

Investigation eliminated other suspects systematically: pre-commit (uses `checkout -- .` + patch files, not stash), autostash via rebase/merge (disabled via `GIT_CONFIG` env vars), direct stash calls (wrapper blocks for non-integrator roles), daemon GitPython (only calls read-only `stash("list")`). A stash watchdog polling `.git/refs/stash` caught the test suite as the actual culprit.

## Decision

Adopt a layered set of fixes plus defense-in-depth measures:

- **Test isolation:** all stash tests use `tmp_path` temp repos via `_make_branch_repo()`. Stash entries stay in temp repos, cleaned by pytest.
- **mark-phase auto-commit:** work phase state writes commit `state.yaml` atomically in the worktree with `--no-verify`. Idempotent writes skip the commit.
- **Worktree-preferring state IO:** `read_phase_state` and `write_phase_state` check if `trees/{slug}` exists and route there, preventing state drift between main and worktree.
- **Canonical project root resolution:** `mark-phase` resolves the project root via `git --git-common-dir` before looking for worktrees, preventing double-nesting when called from inside a worktree.
- **Autostash prevention in wrapper:** `GIT_CONFIG_COUNT` env vars inject `rebase.autoStash=false` and `merge.autoStash=false` for every git command.
- **Autostash prevention in GitPython:** `no_autostash_env()` helper and explicit `--no-autostash` flags on merge and pull-rebase calls.
- **Pre-merge dirty check:** `_merge_origin_main_into_worktree` commits pending changes before merging, with a warning log if the worktree was dirty.
- **Wrapper observability:** `TELECLAUDE_GIT_WRAPPER_LOG` logs every git command through the wrapper with role, subcommand, args, and cwd.
- **Stash watchdog:** background poll of `.git/refs/stash` with process tree capture on change.
- **Permission model (three tiers):** DESTRUCTIVE blocked for all roles (restore, clean, switch, reset, revert); PROTECTED integrator-only (stash, commit on main, push on main); RESTRICTED orchestrator cannot commit on any branch.

## Consequences

**Invariants now load-bearing:**

1. No test creates git state in the shared repo. All tests that call git operations must use `tmp_path` fixtures.
2. All state writes prefer worktrees. `write_phase_state` routes to the worktree when it exists.
3. mark-phase auto-commits. Work phase state writes are committed atomically.
4. Autostash is disabled everywhere. Both wrapper and GitPython paths.
5. The wrapper is resolved via symlink. Worktree copies are stale and must not be invoked directly.

**Costs:**

- Defense-in-depth means multiple code paths enforce autostash prevention; future agents adding new git-touching code must remember to maintain the env var injection or `no_autostash_env()` helper.
- The stash watchdog adds a background polling overhead (small; only on `.git/refs/stash`).
- The three-tier permission model is operational friction for legitimate stash needs — integrator role only.

**Failure modes to monitor:**

- Test creating shared stash entry — detection via stash watchdog alerts on `.git/refs/stash` changes.
- Stale worktree wrapper invoked directly — detection via wrapper log showing unexpected `cwd` inside a worktree.
- Autostash re-enabled by a config change or new code path — detection via stash watchdog and wrapper logging.
- State drift between main and worktree — detection via `mark-phase` canonical root resolution preventing double-nesting.
