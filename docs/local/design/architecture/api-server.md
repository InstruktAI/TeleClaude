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

A connection's projection options name the resource streams it receives —
sessions, projects with their preparation state, and todos — and whether
soft-removed todos are included. A client selects only the streams its caller
holds command clearance to read, so opening a connection never widens what that
caller can list. An option never names a computer and never widens reach.

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
- **Connection completeness:** an authenticated UI connection that selects the
  session stream receives its complete eligible session snapshot before
  subsequent session changes. Each reconnect establishes that state again from
  the current cache.
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

- **One path per operation:** every operation on state the daemon owns or
  serves from its cache has one daemon-side entry, a route, which admits the
  caller and invokes the domain operation. UI clients — the TUI and the web
  console — reach shared domain state through routes and projections only and
  hold no file authority over it; client-owned presentation state, temporary
  editor buffers, launch authentication and host attachment stay local to the
  client. `telec` runs a domain operation in its own process only where the
  ownership rule in
  `local/projects/teleclaude/design/architecture/cli-invocation-boundary` admits it.
- **Cache correctness is notification coverage:** a committed mutation reaches
  the cache owner through the store's commit hook, which the daemon composes
  into cache materialization and publication; clients reconcile from the
  projection. A write committed outside the daemon process on daemon-served
  state is admitted only where the daemon observes the commit, as it observes
  configuration files through its watcher; otherwise the write goes through a
  route. No response is a freshness barrier: a mutation's success does not
  promise that the next cached read reflects it.
- **Two execution paths, one completion contract:** behind a route the daemon
  either maps the request to an `InternalCommand` and dispatches it, or calls
  the application service or submits the operation directly. Which path is an
  implementation choice per route; the client-visible contract is the response,
  an immediate result or a durable operation receipt
  (`local/projects/teleclaude/design/architecture/command-classification`).

- **Computer-addressed execution:** an HTTP request that names another computer
  is carried whole to that computer before any route runs here, executes there
  through the same route with the person band that computer resolves for the
  relayed principal
  (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`),
  and its response returns unchanged. A request naming this computer, or none, runs here.
  Routes hold no remote path of their own; the boundary owns the one crossing
  (`local/projects/teleclaude/design/architecture/command-classification`).
  Connection projection options are not requests and name no computer.

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
eligible state. Their resource types and removed-entry flag supply the
connection's projection options; their computer field is ignored. This compatibility
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

### Viewer attachment projection

The session DTO projection composes agent runtime's host-access answer with
integration's destination resolved from the serving computer and its current
computer registry. HTTP reads, connection snapshots and incremental session
changes use that same projection. Computer connection-input changes reproject
affected sessions through the existing authorized session stream and serialized
sender, independently of resource refresh completion. The behavioral contract
is `local/projects/teleclaude/spec/feature/integration/viewer-attachment-projection`;
runtime's access meaning is
`local/projects/teleclaude/spec/feature/agent_runtime/host-pane-access`.

This composition follows `sdlc/policy/domain-ownership`: the projection consumes
the runtime answer and registry facts, while the renderer holds local view
intent and observed panes. Peer session records are projected relative to the
serving computer. Published attachment inputs are independent of whether the
consumer has completed a separate computer-resource request.

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

<!-- planned:api-hang-dumps-show-where-requests-wait -->

- A request held past the API watch's in-flight threshold, or event-loop lag
  past its lag threshold (the `api.watch_*` keys in
  `local/projects/teleclaude/spec/teleclaude-config`), makes the watch write a
  hang dump: the complete stack of every thread and the await chain of every
  pending event-loop task, each dump in a file of its own. The file is complete
  on disk before the watch's error record names it, so a forced kill afterwards
  keeps it. Dumps are spaced by the watch's cooldown, and only the newest are
  kept, so a long stall stays bounded on disk. A dump triggered by loop lag
  shows the loop after it resumed, never the frame that blocked it.

<!-- /planned:api-hang-dumps-show-where-requests-wait -->

## See Also

- docs/local/adr/0013-unified-cluster-events.md
- docs/local/spec/feature/tui/session-visibility.md
- docs/local/design/architecture/scoped-roles.md
