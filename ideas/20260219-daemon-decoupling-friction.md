# Daemon Decoupling for get_context — Friction Pattern

**ID:** 20260219-daemon-decoupling-friction
**Status:** Idea
**Severity:** High
**Frequency:** Recurring (reported 2026-02-16)

## The Problem

`get_context` is our most critical knowledge entrypoint, but it depends on MCP, which depends on the daemon being up. When the daemon is offline (restarts, crashes, service issues), we lose access to documented policies, procedures, and project context entirely.

This is a **single point of failure** that undermines agent autonomy and forces workarounds during infrastructure recovery.

### Evidence

- Memory #40 (FRICTION): "get_context is our most critical tool but it depends on MCP, which depends on the daemon being up. When the daemon is down, we lose our knowledge entrypoint entirely."
- Multiple references to daemon downtime impact (port exhaustion, Feb 10-16 invisible failure).

## The Ask

Decouple `get_context` from the daemon so it works even when the MCP server is unavailable. This likely means:

- Hosting doc snippets in a static/fallback location (filesystem, git)
- Using local file reads as fallback when daemon is unavailable
- Preserving current UX (same `get_context` tool, same snippet retrieval)

## Impact

- **Resilience:** Agents can still reason about policy, procedure, and architecture during infrastructure recovery
- **Trust:** Eliminates cascading failures (daemon down → can't access context → decisions made in blind)
- **Autonomy:** Agents retain their decision-making foundation even when systems fail

## Related

- Agent Job Hygiene spec: "MCP tools are gracefully absent when the daemon is down. Jobs must not depend on MCP for core functionality."
- TeleClaude daemon policy: "The daemon must stay up; restarts must be brief and verified."
