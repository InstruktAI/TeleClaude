---
date: '2026-06-11'
number: '32'
description: 'One cluster bus Redis serves both the Local and Cluster scopes; CLUSTER_REDIS_URL is its canonical config name and REDIS_URL configures the same endpoint, and subscriptions separate the co-mingled scopes by filtering on envelope.scope.'
---

# ADR-0032: One Cluster Bus Redis Serves Both Local and Cluster Scopes — ADR

## Context

The v2 event bus design describes three scopes — `Local`, `Cluster`, `Public` —
as three separate Redis client instances, with `Local` a local-host Redis
distinct from the `Cluster` mesh Redis. The running system has one Redis: the
daemon's single Redis endpoint carries both local pub/sub and the cross-host
`cluster.*` channels (ADR-0013), and a mesh shares that one Redis across hosts.
Cross-host delivery over that single Redis is live — workflow and identity events
reach the fleet through it today.

Adding per-envelope `scope` routing had to map the three-scope model onto a
one-Redis reality without losing the cross-host delivery the fleet already
depends on. Treating `Local` and `Cluster` as two distinct endpoints, or making
`Cluster` an optional client that drops when a freshly introduced
`CLUSTER_REDIS_URL` is unset, would silently drop cross-host events on every
existing install that configures only the original Redis variable.

## Decision

One cluster bus Redis serves both the `Local` and `Cluster` scopes. Its canonical
configuration name is `CLUSTER_REDIS_URL`; the original `REDIS_URL` configures the
same endpoint and stays accepted. Only `Public` is a separate endpoint
(`PUBLIC_REDIS_URL`), optional and off by default.

The two names for one endpoint are an expand/contract rename in the sense of
ADR-0026, applied to a configuration variable rather than an event shape: both
names are accepted through the migration window, and `REDIS_URL` is removed only
once the slowest channel has adopted `CLUSTER_REDIS_URL`. Accepting both names
means no existing single-Redis deployment reconfigures anything.

Because `Local` and `Cluster` resolve to one Redis under shared channel keys, a
subscription separates the scopes it requests by filtering decoded envelopes on
`envelope.scope`, rather than by reading distinct Redis instances.

## Consequences

- Cross-host delivery on existing installs survives the scope rollout with no
  configuration change: `Cluster`-scoped emits route to the Redis the original
  variable already names.
- A requested subscription scope set is honored by decode-time `envelope.scope`
  filtering; co-mingled scopes are separated in the reader, not by the transport.
- A later split of `Local` onto its own local-host Redis is a separate decision;
  until that decision is made, the bus design's separate-`Local`-Redis and
  "single-computer installs run Local-only" framing is target-state, not the
  running contract.

## Alternatives Considered

**Separate `LOCAL_REDIS_URL` and `CLUSTER_REDIS_URL` endpoints now.** Rejected:
the running system has one Redis serving both roles; a second endpoint would force
every install to reconfigure and would not match how `cluster.*` is delivered
today.

**Make `Cluster` an optional client that drops when `CLUSTER_REDIS_URL` is unset.**
Rejected: it would silently stop cross-host delivery on every current install that
configures only the original Redis variable — the breakage the cross-version
compatibility work exists to prevent.

## Status

Superseded by ADR-0139
