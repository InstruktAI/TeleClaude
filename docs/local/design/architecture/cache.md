---
description: Daemon-owned in-memory snapshots materialize local source state and remote cluster state for immediate reads and UI projection.
---

# Cache — Design

## Required reads

@docs/local/adr/0013-unified-cluster-events.md

## Purpose

Provide the daemon's consolidated read view of computers, projects, todos,
sessions, and agent availability. The cache is a materialized view, not the
authoritative store of the records it projects. Local records belong to their
database or runtime owners; remote records belong to the peer that supplies them.

## Inputs/Outputs

Inputs are local domain changes, local startup warmup, peer-presence observations,
cluster envelopes, and authoritative peer bootstrap snapshots. Autonomous stale
read refreshes remain owned by the cache and transport refresh path.

Outputs are immediate read snapshots and local cache-change notifications.
Locally originated writes publish cluster changes; materializing a peer's
change does not republish it as locally originated work.

## Invariants

- **Source ownership:** a cached record retains its source computer and domain
  identity; receiving it creates no local write authority over that source.
- **Immediate reads:** reads return the available snapshot without waiting for
  a peer request.
- **Reconciled bootstrap:** an authoritative peer snapshot reconciles that
  peer's cached set, including entries absent from the snapshot.
- **Event materialization:** local notifications and cluster changes update
  snapshots independently of agent activity. Peer discovery bootstraps existing
  open sessions, including idle and headless sessions.
- **No publication loop:** applying a cluster event or peer snapshot suppresses
  cluster re-publication while retaining local cache notifications.
- **Projection ownership:** the API applies viewer eligibility to cache state;
  the cache does not inherit a UI viewer's reach as fleet membership.

## Primary flows

### Local state

Startup warmup reads local authoritative sources. Local domain changes update
their cache snapshots, notify local consumers, and publish the corresponding
cluster state.

### Remote state

Heartbeat identity establishes peer presence. Cold-start and first-peer bootstrap
obtain existing state. The cluster bridge materializes subsequent peer changes.
Applying a snapshot reconciles that peer's set and notifies local consumers.

### UI consumption

The API server reads this consolidated view and projects eligible state under
`local/projects/teleclaude/design/architecture/api-server`.

## Failure modes

- Peer snapshots arrive asynchronously, so a newly opened read may initially
  lack a peer's state. Subsequent cache changes notify local consumers.
- A daemon offline during a cluster publication misses that event until peer
  bootstrap reconciles the state. Session snapshots have no periodic TTL
  recovery; reconnecting a UI alone does not recreate missing cluster state.
- A failed peer bootstrap retains the available cache and remains retryable
  through the transport's bootstrap lifecycle.

## See Also

- docs/local/adr/0013-unified-cluster-events.md
- docs/local/design/architecture/api-server.md
