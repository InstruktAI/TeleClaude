---
id: 'project/procedure/runner-operations'
type: 'procedure'
scope: 'project'
description: 'Self-hosted GitHub Actions runner lifecycle, diagnostics, and recovery.'
---

# Runner Operations — Procedure

## Required reads

@project/procedure/troubleshooting

## Goal

Operate and maintain the self-hosted GitHub Actions runner on MozMini (Mac Mini).

## Preconditions

- SSH access to `morriz@mozmini.local`.
- Runner installed at `~/Apps/actions-runner/`.
- Runner registered with the InstruktAI GitHub org with labels `[self-hosted, macOS, ARM64]`.

## Steps

### Check runner status

1. Verify service is running:

   ```bash
   ssh morriz@mozmini.local 'cd ~/Apps/actions-runner && ./svc.sh status'
   ```

2. Verify runner is online on GitHub:

   ```bash
   gh api orgs/InstruktAI/actions/runners --jq '.runners[] | {name, status, labels: [.labels[].name]}'
   ```

3. Check recent runner logs for errors:
   ```bash
   ssh morriz@mozmini.local 'tail -100 ~/Apps/actions-runner/_diag/Runner_$(date +%Y%m%d)*.log 2>/dev/null | grep -i "error\|fail\|connect"'
   ```

### Restart runner

1. Stop the service:

   ```bash
   ssh morriz@mozmini.local 'cd ~/Apps/actions-runner && ./svc.sh stop'
   ```

2. Start the service:

   ```bash
   ssh morriz@mozmini.local 'cd ~/Apps/actions-runner && ./svc.sh start'
   ```

3. Verify connection within 30 seconds:
   ```bash
   ssh morriz@mozmini.local 'tail -20 ~/Apps/actions-runner/_diag/Runner_*.log | grep -i "listen\|connect"'
   ```

### Verify CI workflow execution

1. Check for queued runs:

   ```bash
   gh run list --limit 5 --json databaseId,status,name
   ```

2. Watch a specific run:

   ```bash
   gh run watch <run-id>
   ```

3. View job logs on failure:
   ```bash
   gh run view <run-id> --log-failed
   ```

### Update runner labels

Runner labels must match workflow `runs-on` arrays. MozMini uses custom labels, not macOS defaults.

| Label         | Source                           |
| ------------- | -------------------------------- |
| `self-hosted` | Auto-assigned                    |
| `macOS`       | Custom (NOT the default `OSX`)   |
| `ARM64`       | Custom (NOT the default `Arm64`) |

To update: GitHub → InstruktAI → Settings → Actions → Runners → MozMini → edit labels.

### Host health prerequisites

Before diagnosing runner issues, verify the host is healthy:

1. Network connectivity (see troubleshooting runbook: ephemeral port exhaustion).
2. Disk space: `ssh morriz@mozmini.local 'df -h /'` — needs >20% free.
3. Load: `ssh morriz@mozmini.local 'uptime'` — check for CPU saturation.

## Outputs

- Runner service status confirmed.
- CI jobs executing on the self-hosted runner.

## Recovery

- Runner offline but service running: likely network issue on host. Fix network first, then restart runner.
- Runner picking up wrong jobs: check org-level runner assignment and repository access settings.
- Jobs queued indefinitely: verify labels match (see label table above). Single-concurrency runner processes one job at a time — other jobs queue behind it.
