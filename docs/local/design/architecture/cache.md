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

The cache owner reconciles local sessions from their current authoritative
source. Startup supplies session identities to the same materialization
capability that consumes local session-change notifications. Started, updated,
closed and failed-close notifications request reconciliation; a historical
notification does not determine the current row's existence or lifecycle.

The materialization operation owns source reads, projection and cache
publication as one serialized operation for a session. Source reads occur
inside that operation; callers supply identities rather than captured rows.
An older materialization cannot overtake a newer published materialization.
Source mutations remain independent transactions, so later invalidations
converge the projection rather than providing a synchronous read-after-write
barrier. This separation follows `sdlc/principle/architectural-defaults` and
`sdlc/policy/domain-ownership`.

A missing local source record permits removal of a locally owned cached row;
it supplies no deletion evidence for a peer-owned record. Retention, deletion,
revival and failed close are read from the owning source's current contract.
Runtime supplies host access under
`local/projects/teleclaude/spec/feature/agent_runtime/host-pane-access`.

Optional external enrichment contributes metadata applicable to the current
assignment. It does not retain publication authority over a captured session
snapshot or establish row existence. Lifecycle materialization proceeds
without awaiting the external provider. Source and assignment reads are
arranged coherently, with lifecycle facts read after other awaited metadata
where the source contract permits. A failed source read preserves the available
cache and remains an observable failed reconciliation.

API connections consume cache notifications and apply viewer projection; local
cache materialization is independent of the request server's lifetime. The
cache publishes the corresponding peer state through its existing replication
contract after local application.

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
