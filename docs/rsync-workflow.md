# Rsync Workflow for Fast Development

This document describes how to use rsync for rapid iteration without committing every change.

## Quick Reference

```bash
# Sync from local development machine to remote computer
rsync -avz --exclude-from=.rsyncignore \
  /path/to/teleclaude/ \
  user@remote:/path/to/TeleClaude/

# Example: Sync from macOS to RasPi
rsync -avz --exclude-from=.rsyncignore \
  ~/Documents/Workspace/morriz/teleclaude/ \
  morriz@raspberrypi.local:/home/morriz/apps/TeleClaude/

# Example: Sync from macOS to RasPi4
rsync -avz --exclude-from=.rsyncignore \
  ~/Documents/Workspace/morriz/teleclaude/ \
  morriz@raspi4.local:/home/morriz/apps/TeleClaude/
```

## What Gets Synced

✅ **Synced files:**
- Python source code (`.py`)
- Documentation (`.md`)
- Requirements files
- Makefile
- Scripts in `bin/`
- Test files

❌ **Excluded files (protected):**
- `config.yml` - Computer-specific configuration
- `.env` - Local secrets and environment variables
- `*.db` - Database files (unique per computer)
- `.git/` - Git repository data
- `.venv/` - Python virtual environment
- `uploads/` - User-uploaded files
- `.history/` - Local file history
- `trees/` - Git worktrees

See `.rsyncignore` for complete list.

## Workflow

### 1. Make Changes Locally

Edit code on your development machine (e.g., MozBook).

### 2. Test with Rsync

```bash
# Dry run first (shows what would be synced)
rsync -avzn --exclude-from=.rsyncignore \
  ~/Documents/Workspace/morriz/teleclaude/ \
  morriz@raspberrypi.local:/home/morriz/apps/TeleClaude/

# If dry run looks good, sync for real
rsync -avz --exclude-from=.rsyncignore \
  ~/Documents/Workspace/morriz/teleclaude/ \
  morriz@raspberrypi.local:/home/morriz/apps/TeleClaude/
```

### 3. Restart Remote Daemon

```bash
ssh -A morriz@raspberrypi.local 'cd /home/morriz/apps/TeleClaude && make restart'
```

### 4. Test Remote

Verify the changes work on the remote computer.

### 5. Commit When Ready

Only commit to git when changes are tested and working:

```bash
git add .
git commit -m "feat: description of working changes"
git push
```

## CRITICAL: Never Sync These

The `.rsyncignore` file protects these files from being overwritten:

1. **config.yml** - Each computer has its own:
   - Computer name
   - Bot username
   - Host
   - Trusted directories (different paths on macOS vs Linux)

2. **.env** - Each computer has its own:
   - Bot token (different bots per computer)
   - Working directory path
   - May have different API keys

3. **Database files** - Each computer maintains its own session state

## Rsync Options Explained

- `-a` - Archive mode (preserves permissions, timestamps, etc.)
- `-v` - Verbose (shows what's being transferred)
- `-z` - Compress during transfer
- `-n` - Dry run (preview without making changes)
- `--exclude-from=.rsyncignore` - Exclude patterns from file
- `--delete` - Delete files on destination that don't exist in source (DANGEROUS, not recommended)

## Common Mistakes to Avoid

❌ **DON'T:**
```bash
# This overwrites config.yml and .env!
rsync -avz /local/teleclaude/ user@remote:/remote/TeleClaude/
```

✅ **DO:**
```bash
# This protects local config files
rsync -avz --exclude-from=.rsyncignore /local/teleclaude/ user@remote:/remote/TeleClaude/
```

## Multi-Computer Sync

To sync to multiple computers:

```bash
#!/bin/bash
# save as: sync-to-all.sh

TARGETS=(
  "morriz@raspberrypi.local:/home/morriz/apps/TeleClaude"
  "morriz@raspi4.local:/home/morriz/apps/TeleClaude"
)

for target in "${TARGETS[@]}"; do
  echo "Syncing to $target..."
  rsync -avz --exclude-from=.rsyncignore \
    ~/Documents/Workspace/morriz/teleclaude/ \
    "$target/"

  # Extract host for SSH
  host=$(echo $target | cut -d: -f1)
  path=$(echo $target | cut -d: -f2)

  echo "Restarting daemon on $host..."
  ssh -A "$host" "cd $path && make restart"
done
```

## When to Use Rsync vs Git

**Use Rsync when:**
- Iterating quickly on a feature
- Testing changes on remote hardware
- Changes not yet ready to commit
- Want to test before committing

**Use Git when:**
- Changes are tested and working
- Ready to share with others
- Want to deploy to all computers
- Changes are ready for production

## Recovery

If you accidentally overwrite local config:

```bash
# Restore from .history backup
cp .history/.env_$(date +%Y%m%d)* .env
cp .history/config.yml_* config.yml  # if config.yml backups exist

# Or restore from git
git checkout -- config.yml
# (.env is not in git, use backups only)
```
