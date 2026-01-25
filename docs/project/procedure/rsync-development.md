---
id: procedure/rsync-development
type: procedure
scope: project
description: High-speed iteration workflow using rsync instead of git push/pull.
---

# Rsync Development — Procedure

## Goal

- Sync changes to a remote computer quickly during active development.

- Remote computers are defined in `config.yml` under `remote_computers`.
- SSH access is available and uses agent forwarding (`-A`).

1. Sync changes: `bin/rsync.sh <computer-name>` (uses `.rsyncignore`).
2. Restart daemon: `ssh -A <remote> 'cd <teleclaude_path> && make restart'`.
3. Verify: monitor logs or check status remotely.

- Remote instance updated and running the latest code.

- If sync fails, check SSH connectivity and `config.yml` mapping, then retry.

- TBD.

- TBD.

- TBD.

- TBD.

## Preconditions

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
