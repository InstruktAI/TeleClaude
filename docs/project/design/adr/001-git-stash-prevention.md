---
id: 'project/design/adr/001-git-stash-prevention'
type: 'design'
scope: 'project'
description: 'ADR: git stash prevention in multi-worktree environment — root cause, defense-in-depth, and permission model.'
---

# Git Stash Prevention (ADR-001) — Design

## Required reads

- @docs/project/design/architecture/git-wrapper.md

## Purpose

**Status:** Accepted — **Date:** 2026-03-20

Phantom git stash entries kept appearing in the shared repository stash, blocking the
work state machine's stash-debt precondition check. Multiple agents across multiple
worktrees were affected. The stash is repo-wide — an entry created in one worktree
blocks all worktrees.

### Root cause

`tests/unit/install/test_git_wrapper_permissions.py` ran `git stash` through the
wrapper to test permission enforcement. The `test_integrator_allowed` test used
`role="integrator"` which allows stash — and created a REAL stash entry in the
shared repo-wide stash. No `cwd` was set, so the stash landed in the project
repository.

When `run_build_gates` ran `make test` in a worktree, the test suite resolved the
wrapper from `Path(__file__).parents[3]` — which in a worktree pointed to the
worktree's stale copy of the wrapper (frozen at worktree creation time). This old
wrapper had different permission rules, compounding the problem.

### Investigation

Systematic elimination:

1. **Pre-commit** — uses `checkout -- .` + patch files, NOT `git stash`. Eliminated.
2. **Autostash (rebase/merge)** — disabled via `GIT_CONFIG` env vars in wrapper
   and `no_autostash_env()` in GitPython. Eliminated.
3. **Direct `git stash` calls** — wrapper blocks for non-integrator roles. Eliminated.
4. **Daemon GitPython** — only calls `stash("list")` (read-only). Eliminated.

A stash watchdog (polling `.git/refs/stash` with process tree capture) caught the
actual culprit: the **test suite**.

## Inputs/Outputs

**Inputs:**

- Git stash operations from any agent session or test run
- `TELECLAUDE_SYSTEM_ROLE` environment variable (role for wrapper permission checks)
- `GIT_CONFIG_COUNT/KEY/VALUE` env vars (autostash prevention injection)

**Outputs:**

- Blocked stash operations for non-integrator roles (wrapper enforcement)
- Disabled autostash via config injection at wrapper and GitPython levels
- Atomic state commits in worktrees via mark-phase auto-commit
- Wrapper invocation logs when `TELECLAUDE_GIT_WRAPPER_LOG` is set

## Invariants

These must hold going forward:

1. **No test creates git state in the shared repo.** All tests that call git
   operations must use `tmp_path` fixtures.
2. **All state writes prefer worktrees.** `write_phase_state` routes to the
   worktree when it exists.
3. **mark-phase auto-commits.** Work phase state writes are committed atomically.
4. **Autostash is disabled everywhere.** Both wrapper and GitPython paths.
5. **The wrapper is resolved via symlink.** Worktree copies are stale and must
   not be invoked directly.

## Primary flows

### Immediate fixes

- **Test isolation:** All stash tests use `tmp_path` temp repos via
  `_make_branch_repo()`. Stash entries stay in temp repos, cleaned by pytest.
- **mark-phase auto-commit:** Work phase state writes commit state.yaml
  atomically in the worktree with `--no-verify`. Idempotent writes (no change)
  skip the commit.
- **Worktree-preferring state IO:** `read_phase_state` and `write_phase_state`
  check if `trees/{slug}` exists and route there, preventing state drift
  between main and worktree.
- **Canonical project root resolution:** `mark-phase` resolves the project
  root via `git --git-common-dir` before looking for worktrees, preventing
  double-nesting when called from inside a worktree.

### Defense-in-depth

- **Autostash prevention in wrapper:** `GIT_CONFIG_COUNT` env vars inject
  `rebase.autoStash=false` and `merge.autoStash=false` for every git command.
- **Autostash prevention in GitPython:** `no_autostash_env()` helper and
  explicit `--no-autostash` flags on merge and pull-rebase calls.
- **Pre-merge dirty check:** `_merge_origin_main_into_worktree` commits
  pending changes before merging, with a warning log if the worktree was dirty.
- **Wrapper observability:** `TELECLAUDE_GIT_WRAPPER_LOG` logs every git
  command through the wrapper with role, subcommand, args, and cwd.
- **Stash watchdog:** Background poll of `.git/refs/stash` with process tree
  capture on change.

### Permission model

Three-tier git wrapper permissions:

- **DESTRUCTIVE** — blocked for all roles (restore, clean, switch, reset, revert)
- **PROTECTED** — integrator only (stash, push on main), integrator+system (commit on main)
- **RESTRICTED** — orchestrator cannot commit on any branch

## Failure modes

- **Test creates shared stash entry:** If a test uses the real repo instead of
  `tmp_path`, a stash entry lands in the shared repo-wide stash and blocks all
  worktrees. Detection: stash watchdog alerts on `.git/refs/stash` changes.
- **Stale worktree wrapper invoked:** Worktree copies of the wrapper are frozen
  at worktree creation time. If invoked directly (bypassing PATH symlink), they
  enforce outdated permission rules. Detection: wrapper log shows unexpected
  `cwd` inside a worktree.
- **Autostash re-enabled:** A git config change or new code path re-enables
  autostash, creating silent stash entries during merge/rebase. Detection:
  stash watchdog and wrapper logging.
- **State drift between main and worktree:** If `write_phase_state` fails to
  detect the worktree, state.yaml diverges between main and the worktree.
  Detection: `mark-phase` canonical root resolution prevents double-nesting.
