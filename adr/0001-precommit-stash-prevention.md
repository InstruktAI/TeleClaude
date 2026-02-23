# ADR-0001: Pre-commit Stash Prevention

**Date:** 2026-02-23
**Status:** Accepted

## Context

Pre-commit's `staged_files_only.py` contains an internal stash mechanism that saves unstaged changes as a binary diff patch, runs `git checkout -- .` to clear the working tree, executes hooks on staged-only files, then tries `git apply` to restore the patch. When the apply fails (deleted files, conflicts with hook-formatted changes), unstaged work is permanently destroyed.

This caused repeated data loss during agent commits — entire change sets wiped silently when hooks ran against a working tree with both staged and unstaged tracked files. The git wrapper (`~/.teleclaude/bin/git`) blocks `git stash` at the shell level, but pre-commit bypasses it by calling git directly via `subprocess.Popen` through its own PATH resolution.

## Decision

Replace the overlap guard (which only caught files that were both staged AND unstaged with ACM filter) with a strict stash prevention guard that blocks commits when ANY tracked files have unstaged changes.

The guard lives in `.git/hooks/pre-commit` and runs before pre-commit's Python code. It checks `git diff --name-only` — if anything comes back, the commit is rejected with a clear message listing the unstaged files.

The source of truth is `teleclaude/project_setup/hooks.py`, deployed to all machines via `telec init`. It includes migration logic to detect and replace the old `teleclaude-overlap-guard` marker.

## Alternatives Considered

1. **Monkey-patch `staged_files_only.py`** — Replace the context manager with a no-op in the installed package. Fragile: breaks on every pre-commit upgrade.

2. **Environment variable to disable stash** — Searched pre-commit source for a built-in flag. None exists.

3. **Keep the overlap guard but extend filters** — The old guard only checked ACM filters, missing deletions. Could extend it, but still allows unstaged changes that don't overlap staged files — which still triggers the destructive stash path.

## Consequences

- Agents must `git add` all tracked changes before committing. Selective staging with a dirty working tree is no longer possible.
- Pre-commit's `_unstaged_changes_cleared()` always takes the safe `retcode == 0` path — no patch created, no checkout, no data loss.
- Formatting hooks see the full working tree (staged = unstaged = everything). A formatter might touch files not intended for the commit — cosmetic, not destructive.
- Aligns with existing policy: task-scoped commits where everything is staged.
