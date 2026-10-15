---
description: 'Self-hosted GitHub Actions runner lifecycle, diagnostics, and recovery.'
visibility: 'public'
---

# Runner Operations — Procedure

## Required reads

@docs/local/procedure/troubleshooting.md

## Goal

Operate and maintain the self-hosted GitHub Actions runner on MozMini (Mac Mini).

## Preconditions

- SSH access to `morriz@mozmini.local`.
- Runner installed at `~/Apps/actions-runner/`.
- Runner registered with the InstruktAI GitHub org with labels `[self-hosted, macOS, ARM64]`.

<!-- planned:full-acceptance-on-self-hosted-runner -->

- Tart installed on the runner host with the macOS base image the CI
  verification controllers clone; standalone CI acceptance and release installer
  proof each run inside a disposable virtual machine created from it.
- The runner executes those two jobs one at a time, so the host runs at most
  one such macOS machine, at the processor and memory allocation its workflow
  declares. That machine runs concurrently with the Fleet's Linux guests. The
  Fleet's guest partition, qualified under the release execution steps below,
  leaves that allocation and the host's own reserve free.

<!-- /planned:full-acceptance-on-self-hosted-runner -->

## Steps

### Release execution destination

1. Inspect the repository routing setting named by the release workflow and the
   selected runner destination. Discover the runner host through
   `telec computers list` and its project through `telec projects list`.
2. Qualify the Ubuntu guest base, scoped runner registration, resource partition,
   toolchain and credential-free native confinement before selecting owned
   execution for a controlled dry-run. Use the pinned Fleet release's validation
   and status surfaces; upstream operations are described in its guides.
3. Through the existing release workflow, retain a complete owned dry-run's
   provider and encrypted-settlement results, exact-candidate lint and full
   runtime acceptance, installer proof, and interrupted-run cleanup/recovery
   evidence before enabling unattended owned publication
   (`local/projects/teleclaude/spec/feature/release/publication`).
4. Operate controller installation and lifecycle through the project's make
   targets (`local/projects/teleclaude/policy/agent-service-control`). Inspect
   durable guest and cleanup state before considering a failed run settled.
5. Change the single routing setting to select the compatible hosted destination
   when hosted execution is desired. The release verification and authentication
   contracts remain owned by
   `local/projects/teleclaude/spec/feature/release/publication`.

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

<!-- planned:full-acceptance-on-self-hosted-runner -->

- Disposable verification machine left behind after a cancelled or crashed run:
  the full runtime acceptance run deletes its own leftovers in its final cleanup
  step and again before its next start. `tart list` on the runner host shows
  any remaining machine; delete only machines the CI controllers created, never
  another machine on the host.

<!-- /planned:full-acceptance-on-self-hosted-runner -->

## See Also

- https://github.com/vitalyiegorov/tart-runner-fleet/blob/main/INSTALL.md
- https://github.com/vitalyiegorov/tart-runner-fleet/blob/main/docs/LINUX_BASE_IMAGE.md
- https://github.com/vitalyiegorov/tart-runner-fleet/blob/main/docs/OPERATIONS.md
