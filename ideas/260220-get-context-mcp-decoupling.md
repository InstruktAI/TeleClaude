---
title: Decouple get_context from MCP dependency
date: 2026-02-20
priority: high
status: unresolved
---

## Context

Memory #40 (Feb 16) identifies a critical usability friction: **get_context depends on MCP, which requires the daemon to be running.**

When the daemon goes down:

- Our most important tool becomes unavailable
- Agents lose knowledge retrieval entirely
- Users cannot use `teleclaude__get_context` to bootstrap context

This is a recurring frustration point across agent sessions.

## Problem Statement

### Current Dependency Chain

```
get_context (MCP tool)
  ↓
mcp_client.py (requires MCP connection)
  ↓
daemon (must be running)
  ↓
socket /tmp/teleclaude-api.sock
```

**Failure mode:** Daemon down → socket missing → get_context fails → agents operate without knowledge layer.

### User Impact

- Agents cannot load policies, procedures, or architecture context when daemon is down.
- Emergency recovery is harder (need daemon up to understand daemon issues).
- Context retrieval, the most universal tool, is the first to disappear.

### Contradiction with Job Hygiene

Job spec says: "MCP tools are available when the daemon is running, **gracefully absent when the daemon is down**."

But get_context is so critical that its absence violates the spirit of "graceful degradation."

## Solution Directions

### Option A: Snapshot + Local Fallback

Maintain a local filesystem snapshot of context snippets:

- Periodic snapshot: `~/.teleclaude/docs/` → embedded JSON or SQLite
- Agent has local index as fallback when daemon is down
- Trade-off: 5-minute staleness for availability

**Pros:**

- Works when daemon is down
- Minimal latency
- Offline-first model

**Cons:**

- Snapshot staleness
- Requires sync discipline
- Disk space overhead

### Option B: Standalone Context Service

Run context retrieval as a separate lightweight service:

- Minimal footprint
- Can restart independently of main daemon
- Own database connection (no scheduler dependency)

**Pros:**

- Isolates failure mode
- Always available unless explicitly stopped
- Can be hardened separately

**Cons:**

- New service to manage
- Cross-process coordination
- More complex deployment

### Option C: Read Direct from Docs

Make get_context read directly from `~/.teleclaude/docs/` without MCP:

- Use local file scanning (Glob + Grep)
- No daemon dependency
- Slower but resilient

**Pros:**

- Simplest implementation
- No new services
- Single source of truth (filesystem)

**Cons:**

- Slower (file I/O instead of indexing)
- Lacks query optimization
- May be too slow for regular use

## Related

- Memory #40: Decouple get_context from MCP dependency
- docs/project/policy/mcp-connection-management.md
- MCP tool architecture
