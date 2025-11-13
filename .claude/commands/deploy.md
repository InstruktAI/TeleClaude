---
description: Push to GitHub and deploy to all TeleClaude machines
---

You are now in **deploy mode**. This commits any changes, pushes to GitHub, and deploys to all machines.

## Step 1: Commit Changes (if needed)

Check if there are uncommitted changes:

```bash
git status --porcelain
```

If there are uncommitted changes → **invoke `/commit` command** to create a commit

If no uncommitted changes → proceed to Step 2

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

## Step 4: Cache Deployment Targets (BEFORE Restart)

**CRITICAL:** Get computer list and paths BEFORE restarting (MCP may disconnect during restart)

1. Get list of computers: `teleclaude__list_computers()`
2. For each computer, get teleclaude project path: `teleclaude__list_projects(computer)`
3. Cache this information in memory for use in Step 6

## Step 5: Restart Local TeleClaude & Claude Code

Restart the local TeleClaude daemon and Claude Code session:

```bash
make restart
```

This ensures:
- Local daemon runs latest code
- Claude Code session reconnects MCP servers automatically
- Work continues immediately with "continue" message

Wait 5 seconds for services to stabilize before proceeding.

## Step 6: Deploy to All Remote Machines

**Try MCP deployment first (if reconnected after restart):**

```
teleclaude__deploy_to_all_computers()
```

This will:
- Send deploy command to all computers via Redis
- Each computer: `git pull` → restart daemon
- Return deployment status for each machine

**If MCP deployment unavailable after restart, fall back to SSH deployment:**

Use cached computer list and paths from Step 4 to deploy via SSH.

**IMPORTANT:** Use 10 second timeout per computer and wait for deployment to complete:

```bash
# For each computer, run with timeout and wait
ssh -A <computer> 'cd <teleclaude-path> && git pull && make restart && sleep 5 && pgrep -f teleclaude.daemon'
```

**CRITICAL:**
- Use `-A` flag for SSH agent forwarding
- Use timeout of 10000ms for each SSH command
- Wait 5 seconds after restart for daemon to stabilize
- Check final status with `pgrep` after wait period

Parse output to report deployment status for each machine (success/failure, new PID)

## Step 7: Report Status

After deployment completes, report:

- Pull status (up-to-date / merged commits / rebased)
- Push status (success/failure)
- Deployment status for each machine (computer name, status, PID)
- Any errors encountered

## Important Notes

- **Automatically commits changes** - If uncommitted changes exist, creates a commit first
- Use this when you're ready to deploy changes to production (all machines)
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
