---
description: The shared local HTTP and WebSocket API exposes viewer-authorized daemon state to UI clients and routes mutations through their owning command contracts.
---

# API Server — Design

## Required reads

@docs/local/adr/0013-unified-cluster-events.md

## Purpose

Provide the common daemon boundary for CLI reads, UI state projection, and
typed command submission. The TUI and other UI clients consume the same
WebSocket contract; client presentation does not choose fleet membership or
state-delivery eligibility.

Session-view behavior is owned by
`local/projects/teleclaude/spec/feature/tui/session-visibility`. The daemon's
consolidated cache receives local source changes and remote cluster state under
`local/projects/teleclaude/design/architecture/cache`. Command response modes
remain owned by
`local/projects/teleclaude/design/architecture/command-classification`.

Memory and MCP routes share the API server lifecycle. MCP connections and tool
execution remain owned by the daemon's lazy MCP runtime.

## Inputs/Outputs

Inputs are authenticated caller identity, HTTP resource queries, typed mutation
requests, connection projection options, and daemon cache notifications.

Outputs are resource snapshots, viewer-authorized WebSocket state changes,
command results or durable receipts, and secret-safe error responses. Existing
WebSocket event DTOs own their wire shapes. A session snapshot without a computer
partition denotes the viewer's complete eligible set across the consolidated
cache.

HTTP session and bootstrap reads remain available for existing callers. They do
not control or repair the session collection of a UI consuming the WebSocket
session stream.

## Invariants

- **Daemon-owned fleet:** peer discovery and cache population are independent of
  whether a UI is connected or requests a particular computer.
- **Viewer-authorized projection:** snapshot selection, session changes,
  activity, and project refreshes apply the existing identity reach and audience
  policies. Computer ownership in a delivered record describes its source; it
  is not a client delivery subscription.
- **Connection completeness:** an authenticated UI connection receives its
  complete eligible session snapshot before subsequent session changes. Each
  reconnect establishes that state again from the current cache.
- **One delivery order:** snapshots and changes use the existing per-connection
  serialized sender. Deferred cache notifications cannot replay older row state
  over a newer snapshot or change.
- **Live eligibility:** declaration changes reconcile the connection's session
  projection from current reach. Closure cleanup remains available for sessions
  previously delivered to the connection.
- **Cache-owned reads:** initial projection does not wait on peer requests.
  Remote state arriving after connection is projected as the cache changes.
- **Shared client contract:** the same identity, DTOs, snapshot semantics, and
  event ordering serve the TUI and future UI consumers.
- **Safe command boundary:** UI projection changes no mutation authority,
  command response mode, or durable-operation lifecycle.

## Primary flows

### Connection and session state

The API accepts the connection's existing caller identity, resolves viewer
eligibility, and creates the existing serialized sender. It captures the
eligible consolidated session set and queues the complete snapshot before
enabling session-change delivery. Cache changes thereafter select recipients
by current reach and audience policy and queue current row state in the same
sender. Reconnection and reach reconciliation follow the same projection path.

Legacy WebSocket subscription messages are accepted during the local
client/server transition, without establishing computer membership or gating
eligible state. They preserve existing projection options. This compatibility
surface is retained through the next minor release after delivery and assessed
for retirement once deployed clients no longer send it.

### Peer discovery and resource changes

Heartbeat discovery updates the daemon's computer registry. Peer bootstrap and
cluster events populate the daemon cache without UI interest registration.
Computer registry notifications reach connected UI viewers, and session rows
arriving from a peer follow the ordinary session projection path. Project and
todo refresh notices retain their current resource and reach semantics.

### HTTP reads and command submission

HTTP reads use their existing query owners. Mutations retain their typed
command or lifecycle intent handoff; routes derive the response from the
command's declared response mode. The API does not acquire ownership of
session lifecycle, peer storage, or external adapter delivery.

## Failure modes

- An offline peer or an incomplete peer bootstrap limits the state available
  in the cache. The UI reflects later cache arrivals through the same stream.
- A WebSocket disconnect interrupts live delivery. Reconnection replaces the
  client's session view from the current authorized snapshot.
- An unresolved viewer reach closes that projection fail-closed under the
  existing reach-resolution contract.
- A sender failure closes and cleans up that connection. Existing command and
  operation records remain independent of UI delivery.
- Cache, cluster, command, and MCP recovery retain their owning contracts;
  opening a UI connection adds no recovery authority or peer-polling loop.

## See Also

- docs/local/adr/0013-unified-cluster-events.md
- docs/local/spec/feature/tui/session-visibility.md
- docs/local/design/architecture/scoped-roles.md
