---
description: Allowed moments for remote cache refresh requests.
id: teleclaude/policy/cache-refresh-strategy
scope: project
type: policy
---

# Cache Refresh Strategy — Policy

## Rule

- @docs/architecture/cache

Allow remote refresh requests only at explicit moments; serve from cache otherwise.

1. **Startup warmup (once per daemon start)**
   - Trigger a remote pull to warm the cache after daemon startup.

2. **Heartbeat digest change (per peer)**
   - When a peer heartbeat digest changes, allow a refresh for that peer.

3. **First subscription interest (per peer + data type)**
   - When a client first subscribes to a remote computer's data type, allow one refresh.

4. **TTL expiry on access (per peer + data type)**
   - If cached data is stale and accessed, allow a refresh.

- Serve from cache only. No remote calls.

- Coalesce concurrent refreshes for the same peer + data type.
- Enforce a cooldown between refreshes per peer + data type.

- TBD.

- TBD.

- TBD.

- TBD.

## Rationale

- TBD.

## Scope

- TBD.

## Enforcement

- TBD.

## Exceptions

- TBD.
