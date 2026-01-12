# Requirements: startup-cache-hook-fixes

## Problem Statement

Two bugs affecting multi-computer functionality:

1. **Missing active_agent on manual agent starts**: When a user creates a TeleClaude session via Telegram (`/new_session`) then manually starts Claude Code inside tmux, the hook fires but the session has no `active_agent` set. The daemon crashes with "Session X missing active_agent metadata" instead of handling gracefully.

2. **Empty computer cache on startup**: Remote computers never appear in cache because `discover_peers()` isn't called on Redis adapter startup. The cache population only happens as a side effect of pushing session events, which means new daemons start with empty caches.

## Requirements

### Bug 1: Hook Agent Propagation

- R1: Hook receiver MUST include agent name in payload before enqueuing to `hook_outbox`
- R2: Daemon MUST handle sessions with NULL `active_agent` gracefully when processing hook events
- R3: If `active_agent` is NULL but payload contains agent name, daemon MUST update session and continue
- R4: If both are NULL, daemon MUST log warning and skip (not crash)

### Bug 2: Initial Cache Population

- R5: Redis adapter MUST populate computer cache on startup after connecting
- R6: Redis adapter MUST pull projects for each discovered computer on startup
- R7: Cache population MUST use existing `discover_peers()` and `pull_remote_projects()` methods
- R8: Startup cache population MUST NOT block daemon boot excessively (best effort)

## Success Criteria

1. Manual `claude` start inside existing tmux session produces summary (not error)
2. New daemon startup shows remote computers in cache within seconds
3. MCP `teleclaude__list_computers` returns remote computers immediately after daemon boot
4. No crashes or error messages for the "missing active_agent" scenario

## Out of Scope

- Heartbeat-based ongoing cache updates (future work)
- Changes to heartbeat frequency or TTL
