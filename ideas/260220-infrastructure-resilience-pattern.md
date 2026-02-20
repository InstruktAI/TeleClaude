# Infrastructure Resilience Pattern — Idea

**Status:** Pattern observation
**Date:** 2026-02-20
**Source:** Memory review job analysis

## Observation

Recent memories cluster around three infrastructure fragility vectors:

1. **Port exhaustion** (2026-02-16): silently kills MozMini runner
2. **MCP dependency coupling** (2026-02-16): `get_context` depends on daemon being up
3. **Daemon restart discipline** (2026-02-09): required after code changes, but manual

## Implication

These three issues create a fragility pyramid:

- If ports exhaust → runner silently fails
- If daemon dies → `get_context` breaks (but agents may not know immediately)
- If code changes aren't followed by daemon restart → stale state persists

The system has no automated heal path. When one breaks, the next often follows.

## Questions for Triage

1. Can port exhaustion be detected and auto-remediated?
2. Should `get_context` work without daemon (cached/offline fallback)?
3. Can daemon restart be automated into the deployment pipeline?

## Next Step

Carve out a resilience sprint to audit failure modes and add automated recovery.
