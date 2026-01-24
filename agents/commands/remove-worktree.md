---
description: Remove a git worktree and optionally delete its branch
argument-hint: "[branch-name]"
---

# Remove Git Worktree

Safely remove a git worktree from the `trees/` directory and optionally delete the branch.

## Purpose

Clean up worktrees with validation and optional branch deletion.

## Arguments

- `BRANCH_NAME` (required): Name of the branch/worktree to remove

## Workflow

### 1. Validate Input

- Check BRANCH_NAME is provided
- Construct worktree path: `trees/$BRANCH_NAME`

### 2. Check Worktree Exists

- Verify worktree exists: `git worktree list | grep "trees/$BRANCH_NAME"`
- If not found, error and exit

### 3. Check for Uncommitted Changes

- Run: `git -C trees/$BRANCH_NAME status --porcelain`
- If output exists (uncommitted changes):
  - Ask user if they want to proceed (data will be lost)
  - If no, exit
  - If yes, continue with force removal

### 4. Remove Worktree

- If no uncommitted changes: `git worktree remove trees/$BRANCH_NAME`
- If uncommitted changes and user confirmed: `git worktree remove trees/$BRANCH_NAME --force`

### 5. Verify Removal

- Check worktree removed: `git worktree list | grep "trees/$BRANCH_NAME"`
- Should return nothing

### 6. Handle Branch Deletion

- Check if branch still exists: `git branch --list $BRANCH_NAME`
- If exists, ask user: "Delete branch '$BRANCH_NAME'? (Y/n)"
  - If Y: Try `git branch -d $BRANCH_NAME`
  - If fails (unmerged): Try `git branch -D $BRANCH_NAME` (force)
  - Report which method was used

### 7. Report

```text
✅ Worktree Removed

📁 Location: trees/$BRANCH_NAME (deleted)
🌿 Branch: $BRANCH_NAME

🗑️  Cleanup:
   ✓ Worktree removed from trees/
   ✓ Branch deleted [if deleted]
   OR
   ℹ️  Branch '$BRANCH_NAME' still exists (not deleted)

📝 Notes:
   [If force removed]
   ⚠️  Uncommitted changes were discarded

   [If branch force deleted]
   ⚠️  Branch had unmerged changes (force deleted)
```

## Error Handling

- Missing branch name → "Error: Branch name required"
- Worktree not found → "Error: No worktree at trees/$BRANCH_NAME"
- Currently in worktree → "Error: Cannot remove worktree you're currently in"
- Git errors → Display git error message

## Safety Features

- Warns about uncommitted changes
- Asks confirmation before destructive operations
- Uses safe delete (-d) before force delete (-D)
- Clear reporting of what was deleted
