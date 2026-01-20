---
id: procedure/rsync-development
type: procedure
scope: project
description: High-speed iteration workflow using rsync instead of git push/pull.
---

# Rsync Development Workflow

## Purpose
Enables sub-second synchronization of code changes to remote computers during active development, avoiding WIP git commits.

## Procedure
1. **Sync**: `bin/rsync.sh <computer-name>` (Uses `.rsyncignore` to protect local configs/DBs).
2. **Restart**: `ssh -A <remote> 'cd apps/TeleClaude && make restart'`.
3. **Verify**: Monitor remote logs or check status.

## Rules
- ONLY use the `bin/rsync.sh` wrapper.
- Remote computers MUST be defined in `config.yml` under `remote_computers`.
- ONLY commit to git once the feature is fully tested and working.