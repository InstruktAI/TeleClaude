---
description: Create a git worktree in the trees/ directory
argument-hint: "[branch-name]"
---

# Create Git Worktree

Creates a new git worktree in the standardized `trees/` directory.

## Purpose

Establish a consistent convention for worktree location across all projects and sessions.

## Arguments

BRANCH_NAME: "$ARGUMENTS"

(Required, name of the branch for the worktree)

## Workflow

### 1. Validate Input

- Check BRANCH_NAME is provided
- Validate it's a valid git branch name (no spaces, special chars)

### 2. Setup Directory Structure

- Ensure `trees/` directory exists: `mkdir -p trees`
- Check if `trees/` is in `.gitignore`
  - If not, add it: `echo "trees/" >> .gitignore`

### 3. Check for Existing Worktree

- Check if worktree already exists: `git worktree list | grep "trees/$BRANCH_NAME"`
- If exists, error and exit with message

### 4. Create Worktree

- Create worktree: `git worktree add trees/$BRANCH_NAME $BRANCH_NAME`
  - If branch doesn't exist, this creates it from current HEAD
  - If branch exists, checks it out in the worktree

### 5. Verify Creation

- Confirm worktree created: `git worktree list | grep "trees/$BRANCH_NAME"`
- Confirm directory exists: `ls -la trees/$BRANCH_NAME`

### 6. Report

```text
✅ Worktree Created

📁 Location: trees/$BRANCH_NAME
🌿 Branch: $BRANCH_NAME

📝 Next Steps:
   cd trees/$BRANCH_NAME
   # Work in isolated environment
   # Install dependencies as needed
   # Start services as needed

🗑️  To remove later:
   /remove_worktree $BRANCH_NAME
```

If branch was newly created:

```text
ℹ️  New branch created from current HEAD
```

## Error Handling

- Missing branch name → "Error: Branch name required"
- Worktree already exists → "Error: Worktree already exists at trees/$BRANCH_NAME"
- Git errors → Display git error message
