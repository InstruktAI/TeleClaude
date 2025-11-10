---
description: Create commit, push to GitHub, and deploy to all TeleClaude machines
---

You are now in **commit-deploy mode**. This automates the full deployment cycle:

## Step 1: Create Commit

Use the SlashCommand tool to invoke `/commit`:
```
SlashCommand("/commit")
```

Wait for the commit to complete successfully before proceeding.

## Step 2: Push to GitHub

Run `git push` to push the commit to the remote repository:
```bash
git push
```

If push fails, stop and report the error to the user.

## Step 3: Deploy to All Machines

Use the MCP tool to deploy to all TeleClaude machines:
```
teleclaude__deploy_to_all_computers()
```

## Step 4: Report Status

After deployment completes, report:
- Push status (success/failure)
- Deployment status for each machine (computer name, status, PID)
- Any errors encountered

## Important Notes

- This command does NOT ask for confirmation - it automatically pushes and deploys
- Only use this when you're ready to deploy changes to production
- For local-only commits, use `/commit` instead
- If any step fails, stop and report the error (don't continue to next steps)
