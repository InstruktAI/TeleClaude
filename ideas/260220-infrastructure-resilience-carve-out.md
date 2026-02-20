# Infrastructure Resilience Carve-Out

**Date**: 2026-02-20
**Type**: Actionable finding from memory review
**Priority**: High (two recent critical failures)

## Context

Two critical infrastructure failures discovered Feb 16:

1. Port exhaustion silently killed MozMini runner for 6 days (Feb 10-16)
2. Little Snitch network restrictions blocking git operations

Both failures were invisible to existing monitoring and caused silent service degradation.

## Pattern

Recent memories reveal a cluster of infrastructure gotchas (at least 5 documented):

- Port exhaustion (TIME_WAIT socket accumulation)
- Network filtering (Little Snitch HTTPS blocks)
- SSH key management for CI/CD
- MCP daemon startup delays
- Codex session observability gaps

These are not being proactively monitored or detected. Failures surface only when agents cannot complete work.

## Opportunity

Create a dedicated infrastructure resilience runbook that:

1. Documents known infrastructure failure modes and silent symptoms
2. Provides automated detection/alert triggers for each
3. Includes recovery procedures for each failure class
4. Integrates with existing log-bug-hunter job to catch new patterns

## Next Steps

1. Create `docs/project/procedure/infrastructure-resilience.md` with:
   - Port exhaustion detection and recovery
   - Network filtering diagnostics
   - Daemon health checks
   - Observability gaps in Codex, MCP, rsync

2. Add infrastructure health checks to maintenance cadence

3. Integrate with alerting system (out-of-band-telegram-alerts)

## Related

- Memory #42: Little Snitch blocks HTTPS git
- Memory #41: Port exhaustion silently killed MozMini runner
- Doc: project/procedure/host-health-checks
- Job: log-bug-hunter (extend to infrastructure probing)
