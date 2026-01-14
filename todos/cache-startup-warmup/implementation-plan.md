# Implementation Plan - cache-startup-warmup

## Overview

Add two small features: warmup on daemon startup and digest-based project invalidation.

## Steps

1. [x] **Add Warmup Hook**
   - In `RedisAdapter.start()`, after connection is established, call `refresh_remote_snapshot()`.
   - This fetches projects from all peers immediately on daemon startup.

2. [x] **Generate Project Digest**
   - In `_send_heartbeat()`, compute a digest of local project paths.
   - Use a simple hash (e.g., hash of sorted project paths joined).
   - Add `projects_digest` field to heartbeat payload.

3. [ ] **Track Peer Digests**
   - Add `_peer_digests: dict[str, str]` to `RedisAdapter` to track last-seen digest per computer.

4. [ ] **Detect Digest Changes**
   - In `refresh_peers_from_heartbeats()`, compare received digest to stored digest.
   - If changed, trigger `pull_remote_projects_with_todos()` for that computer.
   - Update stored digest after refresh.

5. [ ] **Tests**
   - Unit test for digest generation (deterministic, stable).
   - Integration test for digest-triggered refresh.
