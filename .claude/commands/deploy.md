---
description: Push to GitHub and deploy to all TeleClaude machines
---

You are now in **deploy mode**. This pushes commits to GitHub and deploys to all machines.

**PREREQUISITE**: All changes must be committed before running this command. If you have uncommitted changes, run `/commit` first.

## Step 1: Verify Clean Working Tree

Check if there are uncommitted changes:

```bash
git status --porcelain
```

If there are uncommitted changes:
- **STOP** and tell the user: "You have uncommitted changes. Run `/commit` first, then try again."
- Do NOT proceed

## Step 2: Git Pull (Handle Remote Changes)

**CRITICAL**: Always pull before pushing to handle remote changes.

Run `git pull --rebase`:

```bash
git pull --rebase
```

**Handle merge conflicts if they occur:**

1. If rebase succeeds with no conflicts → proceed to Step 3
2. If rebase has conflicts:
   - Report the conflicting files to the user
   - Ask user how to resolve (abort and manual fix, or auto-resolve strategy)
   - DO NOT proceed until conflicts are resolved
3. If pull fails with other errors → stop and report

## Step 3: Push to GitHub

Run `git push` to push commits to the remote repository:

```bash
git push
```

If push fails, stop and report the error to the user.

## Step 4: Deploy to All Machines

Use the MCP tool to deploy to all TeleClaude machines:

```
teleclaude__deploy_to_all_computers()
```

This will:
- Send deploy command to all computers via Redis
- Each computer: `git pull` → restart daemon
- Return deployment status for each machine

## Step 5: Report Status

After deployment completes, report:

- Pull status (up-to-date / merged commits / rebased)
- Push status (success/failure)
- Deployment status for each machine (computer name, status, PID)
- Any errors encountered

## Important Notes

- **Commits must exist before running** - Use `/commit` first if needed
- This command does NOT create commits - it only pushes and deploys existing commits
- Only use this when you're ready to deploy changes to production
- For local-only commits without deployment, use `/commit` instead
- If any step fails, stop and report the error (don't continue to next steps)
- Uses `git pull --rebase` to keep linear history (avoids merge commits)

## Typical Workflow

**In worktree** (feature development):
```
/commit  # per task (multiple times)
/commit  # per task
/commit  # per task
```

**After merging to main**:
```
git merge {feature-branch}  # brings all commits to main
/deploy              # push + deploy everything
```
