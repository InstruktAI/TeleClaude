# Automate Infrastructure Reliability Checks — Idea

**Status:** Actionable Finding
**Memory Sources:** IDs 25, 40
**Created:** 2026-02-19

## Problem

Two recurring frustrations about infrastructure reliability:

- **ID 25:** Agents fail to restart daemon after code changes, then validate against stale state
- **ID 40:** get_context depends on MCP/daemon availability; when the daemon is down, the most critical tool becomes inaccessible

Both are high-impact, recurring issues that undermine trust in agent work.

## Insight

**ID 25** is a behavioral problem (agents forget to restart). **ID 40** is an architectural problem (tool availability depends on daemon). Together, they suggest a gap in automation:

1. There's no guard rail forcing daemon restart after code changes
2. There's no fallback for get_context when MCP is unavailable
3. There's no monitoring that alerts when daemon availability drops

## Recommendation

1. **Enforce daemon restart (short-term):** Add a pre-commit hook or linting check that detects daemon/hook code changes and fails CI unless `make restart` has been run and verified.

2. **Decouple get_context from MCP (medium-term):** Per ID 40, get_context should work even when the daemon is down. This may require:
   - Caching doc snippets locally
   - Falling back to filesystem-based doc retrieval
   - Or re-architecting get_context as a standalone service

3. **Monitoring (ongoing):** Add daemon health checks to the heartbeat or CI system so downtime is immediately visible.

## Follow-up

- Evaluate daemon restart hook feasibility
- Prototype get_context fallback mechanism
- Consider alerting on daemon unavailability
