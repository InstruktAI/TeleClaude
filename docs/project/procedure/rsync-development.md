---
id: 'project/procedure/rsync-development'
type: 'procedure'
scope: 'project'
description: 'High-speed iteration workflow using rsync instead of git push/pull.'
---

# Rsync Development — Procedure

## Goal

Sync changes to a remote computer quickly during active development.

## Preconditions

- Remote computers are defined in `config.yml` under `remote_computers`.
- SSH access is available and uses agent forwarding (`-A`).

## Steps

1. Sync changes: `bin/rsync.sh <computer-name>` (uses `.rsyncignore`).
2. Restart daemon: `ssh -A <remote> 'cd <teleclaude_path> && make restart'`.
3. Verify: monitor logs or check status remotely.

## Outputs

- Remote instance updated and running the latest code.

## Recovery

- If sync fails, check SSH connectivity and `config.yml` mapping, then retry.
