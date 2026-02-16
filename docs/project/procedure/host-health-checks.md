---
id: 'project/procedure/host-health-checks'
type: 'procedure'
scope: 'project'
description: 'Diagnostic checks for macOS host health on TeleClaude computers.'
---

# Host Health Checks — Procedure

## Goal

Verify that a TeleClaude computer is healthy at the OS/network level before diagnosing application issues.

## Preconditions

- SSH access to the target computer.
- Connection details from `config.yml` (host, user, teleclaude_path).

## Steps

### 1. Network connectivity

```bash
ssh morriz@mozmini.local 'curl -s -o /dev/null -w "%{http_code}" https://github.com'
```

Expected: `200`. If this fails, the host has a network problem — do not proceed to application diagnostics.

### 2. TCP socket health

```bash
ssh morriz@mozmini.local 'netstat -an | grep TIME_WAIT | wc -l'
```

Healthy: <5,000. Problem: >10,000 indicates ephemeral port exhaustion.

If exhausted, expand the port range:

```bash
ssh morriz@mozmini.local 'sudo sysctl -w net.inet.ip.portrange.first=10000'
```

For persistence, ensure `/etc/sysctl.conf` contains:

```
net.inet.ip.portrange.first=10000
```

### 3. Disk space

```bash
ssh morriz@mozmini.local 'df -h /'
```

Healthy: >20% free. Critical: <5% free.

Top consumers:

```bash
ssh morriz@mozmini.local 'du -sh /tmp ~/Library/Caches ~/Apps/actions-runner/_work 2>/dev/null | sort -rh | head -5'
```

### 4. System load

```bash
ssh morriz@mozmini.local 'uptime && sysctl hw.memsize hw.ncpu'
```

Check load average vs CPU count. Load average > 2x CPU count indicates saturation.

### 5. DNS resolution

```bash
ssh morriz@mozmini.local 'nslookup github.com && nslookup mozmini.local'
```

If external DNS fails but `1.1.1.1` works as resolver, the system DNS is the issue — see troubleshooting runbook.

### 6. Daemon health

```bash
ssh morriz@mozmini.local 'cd ~/Workspace/InstruktAI/TeleClaude && make status'
```

This checks TeleClaude itself. Only run after host-level checks pass.

## Outputs

- Host health assessment with specific metrics.
- Identification of infrastructure-level blockers.

## Recovery

- Port exhaustion: expand range via sysctl (see step 2).
- Disk full: Docker prune, clean runner temp, clear caches.
- DNS failure: flush cache, set fallback DNS (see troubleshooting runbook).
- High load: identify runaway processes with `top -l 1 -n 10`.
