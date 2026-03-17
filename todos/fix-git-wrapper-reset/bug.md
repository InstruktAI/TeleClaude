# Bug: git wrapper allows bare 'git reset' — policy requires blocking all reset variants that move HEAD

## Symptom

git wrapper allows bare 'git reset' — policy requires blocking all reset variants that move HEAD

## Detail

## Problem

The git wrapper at `teleclaude/install/wrappers/git` (lines 115-124) only blocks `git reset --hard|--merge|--keep`. Bare `git reset` and `git reset <commit>` (mixed reset) pass through unchecked.

Policy (version-control-safety) says: 'Never use git checkout, git restore, git reset, git clean, or delete files unless explicitly instructed.'

## Reproduction

In any agent session on main:
```
git add somefile.py
git reset HEAD   # succeeds — should be blocked or scoped
```

## Root cause

The reset guard (lines 115-124) iterates args looking for `--hard|--merge|--keep` flags. When none are present, the command passes through to real git. A bare `git reset <commit>` moves HEAD backward without any flag, silently losing committed work.

## Correct behavior

- `git reset HEAD <path>` (unstaging a file) — **allow** (benign, no HEAD movement)
- `git reset` (bare, no args beyond reset) — **block** (resets index to HEAD, loses staging)
- `git reset <commit>` (mixed reset to older commit) — **block** (moves HEAD, loses commits from working perspective)
- `git reset --hard|--merge|--keep` — **block** (already handled)

## Files

- `teleclaude/install/wrappers/git` — add smarter reset detection
- `tests/unit/install/test_git_wrapper_permissions.py` — add test cases for bare reset and commit-targeted reset

## Latest wrapper commit

e3dc53f29 refactor(git-wrapper): derive permissions from system_role instead of ad-hoc env vars

## Discovery Context

Reported by: manual
Session: none
Date: 2026-03-17

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
