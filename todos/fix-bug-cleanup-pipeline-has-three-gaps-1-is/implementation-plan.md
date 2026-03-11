# Implementation Plan: Bug cleanup pipeline has three gaps

## Overview

Three independent defects in the bug cleanup pipeline block the full lifecycle of bug fix slugs. Each gap prevents a different stage: detection, delivery, and removal. The fix corrects the path check, makes delivery robust to missing roadmap entries, and makes removal best-effort when worktrees are present.

## Gap 1: _is_bug_slug() checks wrong path

**Location:** `teleclaude/core/integration/state_machine.py:402`

**Problem:** The function checks `todos/bugs/{slug}/bug.md` but bugs live at `todos/{slug}/bug.md`. This causes the detection to always return False, forcing the integration machine to attempt delivery on every bug slug, which then fails.

**Fix:** Correct the path from `todos/bugs/{slug}/bug.md` to `todos/{slug}/bug.md`.

**Impact:** Bug slugs are now correctly identified, and delivery is skipped when not needed.

## Gap 2: deliver_to_delivered() fails for items not in roadmap

**Location:** `teleclaude/core/next_machine/core.py:2172-2176`

**Problem:** The function rejects slugs absent from `roadmap.yaml`. Bug fix slugs intentionally skip the roadmap (they are picked up immediately by orchestrators), so this gate always rejects them. No code path handled slugs existing only as a `todos/{slug}/` directory.

**Fix:** When slug is not in roadmap and not already delivered:
- Check if `todos/{slug}/` directory exists
- If it does, proceed to record in `delivered.yaml` instead of returning False
- Move `save_roadmap()` into the else branch so it only runs when an entry was actually removed

**Impact:** Bug fix slugs can now be recorded as delivered without requiring a roadmap entry.

## Gap 3: remove_todo() refuses when worktree exists

**Location:** `teleclaude/todo_scaffold.py:280-286`

**Problem:** The function raises `RuntimeError` when `trees/{slug}/` exists, telling the caller to remove the worktree manually. Bug fix slugs always have an active worktree (that IS the working context), making cleanup impossible through the standard CLI.

**Fix:** Remove the `RuntimeError` guard on worktree presence:
- Proactively remove the worktree with `git worktree remove --force` (best-effort)
- Remove the local branch with `git branch -D` (best-effort)
- Add `found_worktree` to the "anything found" check so a worktree-only slug is recognized as valid
- Allow cleanup to proceed even if some artifacts are missing

**Impact:** Bug fix slugs can now be fully cleaned up through the standard `telec todo remove` command, even with active worktrees.

## Verification

All three fixes preserve the contract:
- **Detection** correctly identifies bug slugs without false positives
- **Delivery** handles items with and without roadmap entries
- **Removal** is best-effort and tolerant of missing artifacts

The fixes are minimal and surgical—no refactoring, no behavioral changes outside the three identified gaps.
