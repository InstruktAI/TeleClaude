# Infrastructure resilience — incident pattern across runners

## Problem

Multiple recurring infrastructure gotchas that disable runners and are painful to diagnose:

1. **Port exhaustion** (Memory #41, Feb 10-16 2026) — MozMini runner silently offline for 6 days due to TCP port exhaustion. The service showed as "running" in launchctl but had zero network connectivity. Requires manual `sysctl` fixes and persistence configuration.

2. **Little Snitch HTTPS blocking** (Memory #42) — Little Snitch blocks git-remote-https and Python3 HTTPS on mozmini, but allows SSH and curl. Requires CLI access configuration via GUI (cannot be managed remotely until authorized once).

3. **Daemon dependency during restarts** — When the daemon goes down for restarts or development, agents lose access to critical tools (get_context, MCP tools), creating cascading failures.

These are not isolated incidents; they point to a deeper resilience gap in distributed TeleClaude deployments.

## Opportunity

Create an infrastructure resilience initiative:

1. **Diagnostic automation** — add health checks that proactively surface port exhaustion, network issues, and other invisible failures
2. **Persistence across restarts** — ensure sysctl and firewall rules survive reboots
3. **Runner hardening** — add watchdog timers and self-diagnostics to detect silent failures
4. **Decoupling critical tools from daemon** — ensure get_context and other essential agent capabilities work offline

## Scope

- Audit all runners for known pain points
- Create diagnostic procedures for operators
- Implement persistence for manually configured fixes
- Add health-check integration to cron runner

## Success criteria

- Runners that go silent are detected within hours, not days
- Infrastructure misconfigurations are surfaced proactively
- All fixes (sysctl, firewall, etc.) persist across reboots
