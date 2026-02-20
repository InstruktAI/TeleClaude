---
title: Infrastructure Operations Runbook — from recent incidents
date: 2026-02-20
priority: high
status: open
---

## Context

Recent memory review identified two critical infrastructure incidents (Feb 16) that should be formalized into operational runbooks:

- **Port exhaustion silently crashed MozMini runner** (offline 6 days, Feb 10-16)
- **Little Snitch blocking HTTPS/Python connections** (SSH workaround required)

Both were invisible to monitoring until root cause analysis. These patterns belong in a formal ops manual, not ad-hoc memories.

## Findings

### Port Exhaustion on macOS

- **Problem:** Default macOS ephemeral port range (49152-65535) = 16K ports only.
- **Symptom:** 31K TCP sockets in TIME_WAIT exhausted range; runner silently offline.
- **Detection:** Service showed running in launchd; visible only via network diagnostics.
- **Fix:** `sudo sysctl -w net.inet.ip.portrange.first=10000` expands to 55K ports.
- **Persistence:** Needs `/etc/sysctl.conf` entry (runtime-only without it).

### Little Snitch on MacOS

- **Problem:** Little Snitch blocks git-remote-https and python3 HTTPS; allows SSH + /usr/bin/curl.
- **Workaround:** Configure git via SSH: `url.git@github.com:.insteadOf=https://github.com/`
- **Deployment:** Generated passphrase-less deploy key at `~/.ssh/id_ci_runner`.
- **CLI Access:** Requires GUI authorization first (Settings > Security > Allow access via Terminal).
- **Config Location:** Encrypted at `/Library/Application Support/Objective Development/Little Snitch/configuration6.xpl`.
- **Limitation:** Cannot be managed remotely until CLI is authorized via GUI once.

## Scope

Create a formal operational runbook that includes:

1. **Symptom detection checklist** for common infrastructure failures
2. **Port exhaustion diagnosis** with `/usr/bin/netstat` and `sysctl` commands
3. **Little Snitch troubleshooting** flow (auth, git config, SSH fallback)
4. **Prevention actions** (persistent sysctl config, monitoring thresholds)
5. **Incident recovery** procedures (runner restart, state verification)

## Related

- Memory #42: Little Snitch blocks HTTPS git
- Memory #41: Port exhaustion silently killed MozMini runner
- docs/project/procedure/troubleshooting.md (likely target for this content)
