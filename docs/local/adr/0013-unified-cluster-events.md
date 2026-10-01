---
date: '2026-06-02'
description: 'Cross-computer state propagation moves to a single ``cluster.*`` Redis pub/sub channel namespace. Local cache becomes a materialized view of cluster events; the legacy heartbeat-digest pull and the per-data-type "interest" gate are retired.'
number: '13'
visibility: 'public'
---

# ADR-0013: Unified Cluster Events Replace Per-Aggregate Cross-Computer Pull — ADR

## Context

The v1 daemon had accreted three different transport patterns for one logical job — keeping every computer's view of sessions, projects, todos, and computer-presence consistent: heartbeat keys with a `projects_digest` change-trigger, request/response over Redis Streams (gated by an in-memory "interest" registration), and a one-directional `PSUBSCRIBE workflow.*` cache invalidation.

The drift caused recurring production incidents: peers failing to discover each other, a repeating crash in the peer-refresh loop, a digest that signalled "something changed" without saying what, and an asymmetry where projects propagated but sessions usually did not. The proximate question — make the TUI a real cross-computer cockpit — collapsed into a deeper one: which single transport pattern should own this domain?

## Decision

All cross-computer state mutation flows through one Redis pub/sub channel namespace, **`cluster.*`**, with the same envelope shape and idempotency discipline as the existing `workflow.*` bridge. The local cache is a materialized view of the cluster event stream, partitioned by computer; the TUI consumes cache changes exactly as before — only the _source_ of cache writes broadens.

- The **heartbeat carries the cross-computer identity fields peers need** (user, host, role, stats), so peer discovery reads identity directly from it — no request/response round-trip.
- A single publish point emits a `cluster.*` event after each local cache write; a single subscriber decodes, dedups, and dispatches by channel category; self-origin events are dropped at dispatch so a local write does not double-apply.
- A **bootstrap snapshot** covers cold-start prefill; request/response is unused in steady state.
- The legacy **interest gate, digest comparison, and the per-aggregate pull round-trip are retired.** Categories propagate symmetrically; the heartbeat is presence-only with full identity.

## Consequences

- One pattern owns cross-computer propagation; a new aggregate plugs in by routing on a new channel prefix.
- The discovery and crash symptoms are structurally gone — discovery no longer depends on a round-trip that could time out.
- Receivers parse a typed envelope rather than an opaque digest plus a pull, so per-event metadata can be carried without inventing new transports.
- Pub/sub is fire-and-forget: a daemon offline when an event publishes misses it until the next bootstrap snapshot. Acceptable for the small clusters targeted; Redis Streams + consumer groups is the escalation if measured misses appear.

## Alternatives Considered

**Keep three transports, fix the bugs in place.** Rejected: the three-transport drift was the root cause, not any single bug; the same class of incident would recur.

**Redis Streams + consumer groups for `cluster.*`.** More correct on durability, but doubles the surface area; the existing bridge uses pub/sub and the bootstrap snapshot covers the offline gap. The natural next ADR if missed-event pain materializes.

**Drop pub/sub; rely on bootstrap + heartbeat-digest pull.** Rejected: the gap between heartbeat ticks is exactly the gap pub/sub closes for near-real-time TUI updates.
