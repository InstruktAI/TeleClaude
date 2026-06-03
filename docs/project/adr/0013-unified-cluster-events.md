---
id: 'project/adr/0013-unified-cluster-events'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '13'
date: '2026-06-02'
adr_status: 'accepted'
description: 'Cross-computer state propagation moves to a single ``cluster.*`` Redis pub/sub channel namespace. Local cache becomes a materialized view of cluster events; the legacy heartbeat-digest pull and the per-data-type "interest" gate are retired.'
---
# ADR-0013: Unified Cluster Events Replace Per-Aggregate Cross-Computer Pull — ADR

## Context

The v1 daemon had accreted three different transport patterns for one logical job — keeping every computer's view of sessions, projects, todos, and computer-presence consistent:

1. **Heartbeat keys (`SETEX` + TTL)** — presence ping plus a `projects_digest` hash used as a change trigger.
2. **Request/response over Redis Streams** — `list_projects_with_todos`, `list_sessions`, `get_computer_info`; pull-on-demand, synchronous, brittle to peer offline. Sessions were additionally gated by an in-memory "interest" registration that only fired when a WebSocket client subscribed to a specific peer.
3. **PSUBSCRIBE `workflow.*`** — v2-Rust → v1-Python cache invalidation introduced when the workflow service moved to v2. Worked exactly the way cross-computer propagation *should* work, but scoped to one direction and one aggregate family.

The symptoms accumulated in production over the v1 lifecycle:

- `discover_peers()` consistently returned 0 computers at TUI WebSocket connect because the `get_computer_info` request/response round-trip timed out or returned stripped data; subsequent heartbeat-driven `ComputerInfo` writes overwrote good data with nulls (heartbeat payload didn't carry identity).
- The peer-refresh background loop crashed with `AttributeError: 'NoneType' object has no attribute 'decode'` whenever a heartbeat key TTL'd between `SCAN` and `GET`; `AttributeError` was not in `_REFRESH_EXCEPTIONS`, so the task died with no respawn.
- The `projects_digest` field was a hash of state masquerading as an event — opaque to receivers, no information about *what* changed, used purely as a "something is different, please pull" trigger.
- The session "interest" gate (`set_interest`/`get_interested_computers`) created an asymmetry: projects propagated whenever a heartbeat digest moved; sessions only propagated when a WS subscription was open. Most users never saw remote sessions because that gate was never registered.

The proximate question — how do we make the TUI a real cross-computer cockpit? — collapsed into a deeper one: which single transport pattern should own this domain?

## Decision

All cross-computer state mutation flows through one Redis pub/sub channel namespace, **`cluster.*`**, with the same envelope shape and idempotency discipline as the existing `workflow.*` v2 bridge. The local `DaemonCache` is a materialized view of the cluster event stream, partitioned by `computer`. The TUI consumes cache change events over WebSocket exactly as before — only the *source* of cache writes broadens.

Concretely:

- **Heartbeat carries the cross-computer `ComputerInfo` fields peers need.** `user`, `host`, `role`, and `system_stats` ship in the heartbeat payload. Excluding `tmux_binary` is intentional: that field is a daemon-local server-start concern; the cross-computer protocol carries only fields a peer needs to reason about presence, SSH identity, and display. `discover_peers` reads identity directly from the heartbeat — no `get_computer_info` request/response round-trip exists.
- **`ClusterBridge` subscribes to `cluster.*`** via `PSUBSCRIBE`, decodes `ClusterEnvelope` (channel, idempotency_key, emitted_at, origin, payload), dedups via an in-memory LRU, and dispatches by channel-prefix category (`session`, `project`, `todo`, `computer`).
- **`ClusterPublisher` is the single emit point** used by `DaemonCache` writers. Every state mutation publishes a `cluster.*` event after the in-memory write. Cache writers accept a `from_cluster=True` flag that the bridge dispatch sink sets to suppress the re-publish leg (closes the round-trip).
- **The bridge short-circuits self-origin envelopes.** Self-published events round-trip through Redis but are dropped at dispatch — the local writer already mutated state and fired WS fanout; re-applying would just double-emit.
- **Bootstrap snapshot survives** for cold-start cache prefill: `refresh_remote_snapshot` schedules `pull_remote_projects_with_todos(peer)` and `pull_remote_sessions(peer)` for every peer at daemon connect. After bootstrap, request/response is unused for steady-state.
- **The "interest" gate, digest comparison, and `get_computer_info` round-trip are all retired.** Categories propagate symmetrically; the heartbeat is presence-only with full identity.

### Delivery scope

The decision above defines the target architecture. Implementation lands in stages so each commit stays daemon-up and reviewable.

**Wired in this push (commits 3451a2cba .. 7646f936f):**

- Heartbeat enrichment + crash hotfix.
- `ClusterBridge` + `ClusterPublisher` infrastructure subscribed/wired in the daemon.
- `cluster.session.{created|updated|closed}` publish on cache writes; bridge dispatch routes session envelopes back into the cache.
- Bootstrap snapshot pulls sessions per peer alongside projects on daemon connect.
- Discovery uses heartbeat-only identity; `get_computer_info` round-trip removed.
- TUI tmux attach SSH-wraps remote sessions using cache-resident identity.

**Tracked but not yet wired (future commits, same envelope shape):**

- `cluster.project.{registered|unregistered}` — projects still propagate via the bootstrap pull + workflow_bridge invalidation; the live publish/apply path is not in this push.
- `cluster.todo.{created|updated|deleted|phase_changed}` — todos similarly rely on bootstrap + workflow_bridge today.
- `cluster.computer.updated` — computer presence still flows through heartbeat keys (the primary path); a complementary event-level update is the long-term direction but not required for the current symptom.
- TUI-to-peer "create session on MozBook" flow. This ultimately shipped through the existing Redis `messages:{computer}` request/response transport rather than through `cluster.session.create_request|created|create_failed` event envelopes; session ownership still propagates back to peers through `cluster.session.{created|updated|closed}`.

The narrowing is intentional: sessions are the cross-computer aggregate with the strongest user-visible win, and shipping one category cleanly proves the pattern. Subsequent commits repeat the same plumbing for the remaining categories using this commit set as the template.

## Consequences

**Positive:**

- One pattern owns cross-computer state propagation. New aggregates plug in by routing on a new channel prefix and adding a cache-write helper — about thirty lines per category.
- The 0-computers symptom is gone: `discover_peers` no longer depends on a request/response leg that could time out. Heartbeat-only identity is read in O(1) per key.
- The recurring `AttributeError` crash is structurally impossible: `refresh_peers_from_heartbeats` now `None`-guards `redis.get` before decode, and `_REFRESH_EXCEPTIONS` widens to include `AttributeError` as belt-and-braces.
- Sessions propagate symmetrically with projects. The WebSocket interest sync that previously gated session pulls becomes dead code, removed in the same change.
- The contract surface narrows: receivers parse a typed envelope rather than a hash digest plus an opaque pull. Future code can carry per-event metadata (request_id, principal, error reason) without inventing new transports.

**Negative:**

- Pub/sub is fire-and-forget. A daemon offline when an event publishes misses it until the next bootstrap snapshot. For the small clusters this codebase targets (2–3 machines), bootstrap covers the gap; if measured missed-event problems appear, we revisit with Redis Streams + consumer groups.
- Every local mutation now round-trips through Redis on the back-leg (self-origin dispatch is a no-op but the network hop happens). The cost is microseconds per mutation; the win is one code path.
- Heartbeat payload size grows from ~150 bytes to ~600 bytes. Negligible for 30 s cadence; documented as a contract change.
- `get_computer_info` is removed from the Redis request/response dispatch table. Internal-only command; no external consumers affected.

## Alternatives Considered

**Keep three transports, fix the bugs in place.** Patching the `AttributeError`, the `_load_peer_info` race, and the interest-gate asymmetry would have addressed the immediate symptoms without changing shape. Rejected: the three-transport drift was the root cause of recurring incidents, not any one bug. A second incident of the same shape would have re-emerged within months.

**Redis Streams + consumer groups for `cluster.*`.** Durable, replayable, per-aggregate ordering guarantees. More correct than PSUBSCRIBE on the persistence axis. Rejected for now (KISS / YAGNI): the existing `workflow.*` v2 bridge uses PSUBSCRIBE, the bootstrap snapshot covers the offline gap, and adopting streams doubles the surface area. If observed missed-event pain materializes — particularly across longer offline windows — this becomes the natural next ADR.

**Make every cache writer have separate outbound / inbound paths.** The plan considered idempotent state-converging writes ("set status to X, regardless of current state") so that round-tripped self-events would be no-ops naturally. Rejected for now: the `from_cluster=True` flag is simpler, the self-origin short-circuit at the bridge avoids the round-trip work entirely, and any future receiver-side merge logic can be added without contract change.

**Drop pub/sub entirely; use only bootstrap + heartbeat-digest pull.** Equivalent functionality to the old design plus the bug fixes. Rejected: the gap between heartbeat ticks is the same gap pub/sub closes for near-real-time TUI updates. Without push, every TUI session-status change would wait up to one heartbeat interval to propagate.
