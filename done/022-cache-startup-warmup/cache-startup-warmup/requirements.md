# Requirements - cache-startup-warmup

## Goal

Ensure remote project data is available immediately after daemon startup, and detect remote project changes via heartbeat digest rather than waiting for TTL expiry.

## Non-Goals

- No changes to TTL values (already configured appropriately).
- No changes to the serve-stale + background-refresh pattern (already works).
- No refactoring of cache architecture.

## Functional Requirements

1. **Warmup on Daemon Startup**
   - When the daemon starts, trigger a remote project fetch for all known peers.
   - Do not wait for the first WebSocket client to connect.
   - Warmup runs asynchronously and does not block daemon startup.

2. **Project Digest in Heartbeat**
   - Each heartbeat includes an opaque digest representing the local project list.
   - Digest is a hash of project paths (stable, deterministic).

3. **Digest-Based Invalidation**
   - When processing a peer's heartbeat, compare the received digest to the last known digest.
   - If digest changed, schedule immediate project refresh for that computer (bypass TTL).
   - Store last-seen digest per computer in memory.

## Acceptance Criteria

- Remote projects are cached within seconds of daemon startup (not on first client connect).
- Heartbeat payload includes `projects_digest` field.
- Adding/removing a project on a remote computer triggers cache refresh on peers within one heartbeat interval (~30s).
