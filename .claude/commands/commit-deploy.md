---
description: Create commit, push to GitHub, and deploy to all TeleClaude machines
---

You are now in **commit-deploy mode**. This automates the full deployment cycle:

## Step 1: Git Pull (Handle Remote Changes)

**CRITICAL**: Always pull before committing to handle remote changes.

Run `git pull --rebase`:
```bash
git pull --rebase
```

**Handle merge conflicts if they occur:**

1. If rebase succeeds with no conflicts → proceed to Step 2
2. If rebase has conflicts:
   - Report the conflicting files to the user
   - Ask user how to resolve (abort and manual fix, or auto-resolve strategy)
   - DO NOT proceed until conflicts are resolved
3. If pull fails with other errors → stop and report

## Step 2: Create Commit

Use the SlashCommand tool to invoke `/commit`:
```
SlashCommand("/commit")
```

Wait for the commit to complete successfully before proceeding.

## Step 3: Push to GitHub

Run `git push` to push the commit to the remote repository:
```bash
git push
```

If push fails, stop and report the error to the user.

## Step 4: Deploy to All Machines

Use the MCP tool to deploy to all TeleClaude machines:
```
teleclaude__deploy_to_all_computers()
```

## Step 5: Report Status

After deployment completes, report:
- Pull status (up-to-date / merged commits / rebased)
- Push status (success/failure)
- Deployment status for each machine (computer name, status, PID)
- Any errors encountered

## Important Notes

- This command does NOT ask for confirmation - it automatically pushes and deploys
- Only use this when you're ready to deploy changes to production
- For local-only commits, use `/commit` instead
- If any step fails, stop and report the error (don't continue to next steps)
- Uses `git pull --rebase` to keep linear history (avoids merge commits)
