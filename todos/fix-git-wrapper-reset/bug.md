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

- Confirmed that `git reset` (bare) and `git reset HEAD~1` (commit-targeted) were allowed by the current git wrapper.
- Verified that the current implementation only blocked `reset` if explicit flags like `--hard`, `--merge`, or `--keep` were present.
- Identified that `git reset` and `git reset <commit>` were passing through because they had no such flags, despite moving HEAD or clearing the staging area.
- Discovered a bash arithmetic bug where `((var++))` returns 1 (error) if `var` is 0, which triggers `set -e` and causes the wrapper to exit silently.

## Root Cause

The git wrapper's `reset` guard was too narrow, only looking for specific destructive flags. It lacked logic to distinguish between "pathspec resets" (which are safe as they only affect the index) and "commit resets" (which are dangerous as they move HEAD). Additionally, a bare `git reset` without arguments was completely unchecked.

## Fix Applied

- Updated `teleclaude/install/wrappers/git` to use a more robust `reset` detection logic.
- The new logic counts non-flag arguments and checks for the `--` separator.
- **Allowed:** Pathspec resets that are unambiguous (using `--` separator or having at least 2 non-flag arguments like `git reset HEAD <path>`).
- **Blocked:** Bare `git reset` and 1-argument resets like `git reset <commit>` or `git reset <path>` without a separator. This forces agents to be explicit and avoid ambiguous commands that might accidentally move HEAD.
- Fixed the bash arithmetic increment bug by using `_non_flag_args=$((_non_flag_args + 1))` instead of `((_non_flag_args++))`.
- Added comprehensive test cases to `tests/unit/install/test_git_wrapper_permissions.py` covering bare reset, commit reset, pathspec reset with `HEAD`, pathspec reset with `--`, and `--hard` reset across different roles.
