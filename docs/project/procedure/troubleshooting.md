---
description: 'Operational runbooks for TeleClaude incidents and infrastructure failures.'
id: 'project/procedure/troubleshooting'
scope: 'project'
type: 'procedure'
---

# Troubleshooting Runbooks — Procedure

## Purpose

Give operators short, direct playbooks for common incidents.

Use this when something is broken now and you need a safe recovery path.

## Allowed control commands

Use only:

- `make status`
- `make restart`
- `instrukt-ai-logs teleclaude --since <window> [--grep <text>]`

If restart is not enough, use:

- `make stop`
- `make start`

## Universal first-response sequence

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m`
3. Identify symptom in runbooks below.
4. Follow that runbook exactly.
5. Verify recovery with `make status` and fresh logs.

## Runbook: MCP tools time out or fail

### Symptom

- MCP tool calls hang, time out, or return backend unavailable errors.

### Likely causes

- MCP socket unhealthy or restarting repeatedly.
- Wrapper reconnecting but backend not stabilizing.

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m --grep "mcp|socket|restart|health"`

### Recover

1. `make restart`
2. Wait for readiness.
3. Re-check MCP logs for repeated restart loops.

### Verify

- MCP calls complete normally.
- No repeating MCP health-check failures in last 2 minutes.

## Runbook: Session output is frozen/stale

### Symptom

- Session is running but output in UI stops updating.

### Likely causes

- Poller watch loop failed.
- Poller not aligned with tmux session state.

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m --grep "poller|output|tmux|watch"`

### Recover

1. `make restart`
2. Re-open affected session and confirm output starts moving.

### Verify

- New output events appear.
- No poller watch errors in recent logs.

## Runbook: Agent finished but no notification/summary

### Symptom

- Agent turn ends, but no stop notification, summary, or downstream update appears.

### Likely causes

- Hook outbox backlog.
- Hook event processing failures.
- Session parser mismatch: `session.active_agent` points to Gemini while hook payload/transcript is Claude JSONL, causing repeated `Extra data` decode failures.

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m --grep "hook|outbox|agent_stop|dispatch|retry"`
3. `instrukt-ai-logs teleclaude --since 5m --grep "Evaluating incremental output|Extra data"`

### Recover

1. `make restart`
2. Watch logs for outbox processing resuming.

### Verify

- Delayed notifications/summaries appear.
- Hook dispatch errors stop repeating.

## Runbook: Headless session cannot be recovered

### Symptom

- Headless session exists, but transcript retrieval/resume fails.

### Likely causes

- Missing native transcript path.
- Native identity not mapped correctly.

### Fast checks

1. `instrukt-ai-logs teleclaude --since 5m --grep "headless|native_session_id|native_log_file|session_map"`
2. Confirm latest hook events carried native identity fields.

### Recover

1. Restart daemon if mapping updates were not applied.
2. Re-trigger hook flow from source session.

### Verify

- Session now has native identity fields populated.
- Session data retrieval works.

## Runbook: Cleanup is not happening (old sessions/artifacts pile up)

### Symptom

- Old sessions remain open forever.
- Orphan tmux/workspace artifacts accumulate.

### Likely causes

- Periodic cleanup loop failed.
- Cleanup errors repeating each cycle.

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 10m --grep "cleanup|inactive_72h|orphan|workspace|voice"`

### Recover

1. `make restart`
2. Wait one cleanup cycle window for normal behavior.

### Verify

- Cleanup logs show successful pass.
- Orphan artifacts no longer increase.

## Runbook: API appears unhealthy

### Symptom

- API-backed tools or TUI calls fail unexpectedly.

### Likely causes

- API interface startup/runtime failure.
- Daemon not healthy overall.

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 2m --grep "api|socket|bind|watch|error"`

### Recover

1. `make restart`
2. If restart fails, run `make stop` then `make start`.

### Verify

- `make status` reports healthy.
- Recent logs show normal API startup without repeated failures.

## Runbook: API restart churn (SIGTERM storm)

### Symptom

- API socket repeatedly disappears/rebinds.
- MCP/API clients show bursts of connection-refused errors.
- Logs show frequent `Received SIGTERM signal...`.

### Likely causes

- External restart trigger loop (automation/operator flow repeatedly issuing restarts).
- Checkpoint-driven housekeeping loops forcing repeated daemon restarts.
- Less likely: internal daemon crash (verify via logs before assuming this).

### Fast checks

1. `make status`
2. `instrukt-ai-logs teleclaude --since 30m --grep "Received SIGTERM signal"`
3. `instrukt-ai-logs teleclaude --since 30m --grep "Removing API server socket|Connection refused"`
4. `instrukt-ai-logs teleclaude --since 30m --grep "API server task crashed|API server task exited unexpectedly"`

### Recover

1. Stop issuing additional restart commands.
2. Perform one controlled restart: `make restart`.
3. If `make restart` reports timeout/degraded, do not immediately chain another restart; check logs for ongoing startup first:
   `instrukt-ai-logs teleclaude --since 2m --grep "Starting TeleClaude daemon|API server listening on /tmp/teleclaude-api.sock"`
4. Validate once: `make status`.
5. Monitor for 10 minutes and confirm SIGTERM events do not continue repeating.

### Verify

- No new `Received SIGTERM signal...` lines in the verification window.
- No sustained connection-refused bursts in MCP/API logs.
- API socket remains present and healthy in `make status`.

## Infrastructure & Environment

These runbooks cover failures outside TeleClaude itself — host OS, network, CI runners — that silently stall operations without producing TeleClaude-level errors.

### Runbook: Ephemeral port exhaustion (macOS)

#### Symptom

- Network calls fail with "Can't assign requested address" or ETIMEDOUT.
- `curl https://github.com` hangs or fails despite Wi-Fi/Ethernet being connected.
- GitHub Actions runner shows "Failed to connect" in logs but launchd reports service as running.

#### Likely causes

- TCP sockets stuck in TIME_WAIT exhaust the ephemeral port range.
- macOS default range is 49152–65535 (only ~16K ports). High-throughput services (Docker builds, runners, CI) can saturate this.

#### Fast checks

1. Count TIME_WAIT sockets:
   ```bash
   netstat -an | grep TIME_WAIT | wc -l
   ```
   Problem threshold: >10,000.
2. Check current port range:
   ```bash
   sysctl net.inet.ip.portrange.first net.inet.ip.portrange.last
   ```

#### Recover

1. Expand ephemeral port range (immediate, survives until reboot):
   ```bash
   sudo sysctl -w net.inet.ip.portrange.first=10000
   ```
2. Verify with `curl https://github.com`.
3. For persistence across reboots, add to `/etc/sysctl.conf`:
   ```
   net.inet.ip.portrange.first=10000
   ```

#### Verify

- `curl https://github.com` returns 200.
- `sysctl net.inet.ip.portrange.first` shows 10000.
- Affected services (runner, Docker) resume normal operation.

### Runbook: Self-hosted GitHub Actions runner silently offline

#### Symptom

- CI jobs stay in "queued" state indefinitely.
- `gh run view <id> --json jobs` shows status `queued` with no runner assignment.
- The runner host reports launchd service as running.

#### Likely causes

- Network failure on the runner host (see port exhaustion above).
- Runner process crashed but launchd did not restart it.
- Runner labels mismatch between workflow `runs-on` and registered labels.

#### Fast checks

1. SSH to runner host and check service:
   ```bash
   ssh morriz@mozmini.local 'cd ~/Apps/actions-runner && ./svc.sh status'
   ```
2. Check runner logs for connection errors:
   ```bash
   ssh morriz@mozmini.local 'tail -50 ~/Apps/actions-runner/_diag/Runner_*.log | grep -i "error\|fail\|connect"'
   ```
3. Verify network:
   ```bash
   ssh morriz@mozmini.local 'curl -s -o /dev/null -w "%{http_code}" https://github.com'
   ```
4. Check registered labels on GitHub:
   ```bash
   gh api orgs/InstruktAI/actions/runners --jq '.runners[] | {name, labels: [.labels[].name]}'
   ```

#### Recover

1. Fix underlying network issue first (if port exhaustion, see runbook above).
2. Restart runner service:
   ```bash
   ssh morriz@mozmini.local 'cd ~/Apps/actions-runner && ./svc.sh stop && ./svc.sh start'
   ```
3. Confirm runner connects:
   ```bash
   ssh morriz@mozmini.local 'tail -20 ~/Apps/actions-runner/_diag/Runner_*.log | grep -i "connect\|listen"'
   ```

#### Verify

- `gh api orgs/InstruktAI/actions/runners` shows runner status `online`.
- Queued jobs start executing.

### Runbook: Little Snitch blocks git/python HTTPS connections

#### Symptom

- `git clone` or `git fetch` hangs for 5 minutes then fails with "Failed to connect to github.com port 443 after 300004 ms: Timeout was reached".
- `python3` HTTPS requests time out.
- `curl https://github.com` works (200).
- CI checkout step hangs indefinitely.

#### Likely causes

- Little Snitch has per-application rules. `/usr/bin/curl` is allowed, but `git-remote-https` and `python3` are not.
- Little Snitch may be in "Silent Mode - Deny" which silently blocks unmatched connections.

#### Fast checks

1. Test which binaries can reach GitHub:
   ```bash
   ssh morriz@mozmini.local 'curl -s -o /dev/null -w "%{http_code}" https://github.com'  # Should work
   ssh morriz@mozmini.local 'GIT_TERMINAL_PROMPT=0 git ls-remote --heads https://github.com/InstruktAI/TeleClaude 2>&1 | head -3'  # Will hang if blocked
   ```
2. Confirm Little Snitch is running:
   ```bash
   ssh morriz@mozmini.local 'pgrep -fl "Little Snitch"'
   ```

#### Recover

**Immediate (SSH bypass):** Configure git to use SSH instead of HTTPS:

```bash
ssh morriz@mozmini.local 'git config --global url."git@github.com:".insteadOf "https://github.com/"'
```

Requires a passphrase-less SSH key (`~/.ssh/id_ci_runner`) registered with GitHub.

**Proper fix (requires physical access to Mac Mini):**

1. Open Little Snitch → Settings → Security → enable "Allow access via Terminal"
2. Then add rules via CLI:
   ```bash
   sudo /Applications/Little\ Snitch.app/Contents/Components/littlesnitch export-model > /tmp/backup.lsbackup
   # Edit JSON to add allow rules for git-remote-https and python3
   sudo /Applications/Little\ Snitch.app/Contents/Components/littlesnitch restore-model --preserve-terminal-access /tmp/backup.lsbackup
   ```
3. Or import a `.lsrules` file (see `/tmp/teleclaude-git-allow.lsrules` on mozmini).

#### Verify

- `git clone --depth=1 https://github.com/InstruktAI/TeleClaude /tmp/test && rm -rf /tmp/test` completes within seconds.
- CI checkout step completes.

### Runbook: Runner label mismatch

#### Symptom

- Jobs stay queued even though the runner is online.
- Runner logs show it is connected but not picking up jobs.

#### Likely causes

- Workflow `runs-on` specifies labels the runner does not have.
- MozMini has custom labels `[self-hosted, macOS, ARM64]` — not the macOS defaults `[self-hosted, OSX, Arm64]`.

#### Fast checks

1. Compare workflow labels with runner labels:
   ```bash
   gh api orgs/InstruktAI/actions/runners --jq '.runners[] | {name, labels: [.labels[].name]}'
   ```
2. Check what the queued job requested:
   ```bash
   gh run view <run-id> --json jobs --jq '.jobs[].labels'
   ```

#### Recover

1. Update workflow `runs-on` to match registered labels, OR
2. Update runner labels via GitHub UI (Settings → Actions → Runners → edit labels).

#### Verify

- Queued jobs start executing after label correction.

### Runbook: DNS resolution failure

#### Symptom

- `curl` and `git` operations fail with "Could not resolve host".
- Network interfaces show connected.

#### Likely causes

- Router/ISP DNS outage.
- `/etc/resolv.conf` or macOS DNS settings misconfigured.
- mDNS conflicts on local network.

#### Fast checks

1. ```bash
   ssh morriz@mozmini.local 'nslookup github.com'
   ```
2. ```bash
   ssh morriz@mozmini.local 'scutil --dns | head -20'
   ```
3. Try public DNS directly:
   ```bash
   ssh morriz@mozmini.local 'nslookup github.com 1.1.1.1'
   ```

#### Recover

1. If public DNS works but system DNS doesn't, add fallback:
   ```bash
   ssh morriz@mozmini.local 'sudo networksetup -setdnsservers "Ethernet" 1.1.1.1 8.8.8.8'
   ```
2. Flush DNS cache:
   ```bash
   ssh morriz@mozmini.local 'sudo dscacheutil -flushcache && sudo killall -HUP mDNSResponder'
   ```

#### Verify

- `nslookup github.com` resolves immediately.
- `curl https://github.com` returns 200.

### Runbook: Disk space exhaustion

#### Symptom

- Builds fail with "No space left on device".
- Docker images and build caches accumulate silently.

#### Fast checks

1. ```bash
   ssh morriz@mozmini.local 'df -h /'
   ```
2. Largest consumers:
   ```bash
   ssh morriz@mozmini.local 'du -sh ~/Library/Caches /tmp ~/Apps/actions-runner/_work 2>/dev/null | sort -rh'
   ```
3. Docker specifically:
   ```bash
   ssh morriz@mozmini.local 'docker system df 2>/dev/null'
   ```

#### Recover

1. Docker cleanup:
   ```bash
   ssh morriz@mozmini.local 'docker system prune -af --volumes'
   ```
2. Runner work directory cleanup (only if no jobs running):
   ```bash
   ssh morriz@mozmini.local 'rm -rf ~/Apps/actions-runner/_work/_temp/*'
   ```

#### Verify

- `df -h /` shows >20% free.
- Builds complete successfully.

## Incident Trail For Next AI

When an incident is non-trivial, preserve the reasoning trail in two places:

1. **Operational runbook context**: this file (`docs/project/procedure/troubleshooting.md`) for stable symptom/recovery steps.
2. **Case trail with timeline + hypotheses**: append to `docs/explore/teleclaude-api-socket-degradation.md`.

Minimum fields for each case-trail entry:

- timestamp window
- symptom
- evidence (exact commands/log patterns)
- root-cause hypothesis + confidence
- change/prototype attempted
- verification result
- next decision

## Escalate when

Escalate immediately if any of the following persists after one controlled restart:

- MCP restart storm continues.
- Hook outbox remains blocked.
- Poller output remains frozen.
- Daemon repeatedly exits during startup.

When escalating, include:

- Exact symptom
- Time window
- Commands run
- Relevant log excerpts from `instrukt-ai-logs`
