---
description: List all git worktrees with status
---

# List Git Worktrees

Display all git worktrees in a clear, organized format.

## Purpose

Provide overview of all worktrees, focusing on those in the standardized `trees/` directory.

## Workflow

### 1. Get Worktree List

- Run: `git worktree list --porcelain`
- Parse output to extract:
  - Worktree path
  - Branch name
  - Commit hash

### 2. Categorize Worktrees

**Main repository:**

- Identify the main worktree (not in trees/)

**Trees worktrees:**

- Filter worktrees in `trees/` directory
- Sort alphabetically by branch name

**Other worktrees:**

- Any worktrees not in main or trees/

### 3. Get Current Branch

- Run: `git branch --show-current`
- Mark current location in report

### 4. Report

```text
📊 Git Worktrees

═══════════════════════════════════════════════

🏠 Main Repository
   📁 <project-root>
   🌿 Branch: <current-branch>
   📝 Commit: <hash-short>

───────────────────────────────────────────────

🌳 Worktrees in trees/

   📁 trees/<branch-name>
   🌿 Branch: <branch-name>
   📝 Commit: <hash-short>

   [Repeat for each worktree in trees/]

───────────────────────────────────────────────

💡 Quick Commands:
   Create: /create_worktree <branch-name>
   Remove: /remove_worktree <branch-name>

═══════════════════════════════════════════════
```

If no worktrees in trees/:

```text
📊 Git Worktrees

🏠 Main Repository
   📁 <project-root>
   🌿 Branch: <current-branch>

ℹ️  No worktrees in trees/

💡 Create your first:
   /create_worktree <branch-name>
```

If there are worktrees outside trees/:

```text
⚠️  Other Worktrees (not in trees/):
   • <path> (<branch>)
```

## Notes

- Main repository always shown first
- Worktrees sorted alphabetically
- Commit hashes shown as short form (7 chars)
- Current working directory indicated if applicable
