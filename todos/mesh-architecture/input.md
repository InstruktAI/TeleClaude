# Mesh Architecture — Input

## Context

TeleClaude today is a single-node system. The notification service processes events
locally via Redis Streams. The daemon API listens on a unix socket. There is no
mechanism for nodes to discover each other or exchange events across instances.

The vision: every TeleClaude instance is a node in a global peer-to-peer mesh. On
install, a node is already a git checkout — it already has a release channel subscription
(alpha/beta/stable). The mesh extends this with runtime peer connectivity for event
propagation, service discovery, and governance participation.

## Discovery: The Bootstrap Problem

Every P2P system needs a way for new nodes to find their first peers. Four tiers,
each independent and resilient:

### Tier 1: DNS-based discovery (primary)

A DNS SRV or TXT record under a controlled domain (e.g., `_mesh._tcp.instrukt.ai`)
returns a list of currently active bootstrap peers. DNS is globally distributed,
cached at every ISP, and nearly impossible to fully take down. Updating the record
updates every future lookup without a code release.

A thin stateless service (Cloudflare Worker or equivalent) receives node registrations
and translates them into DNS record updates. The service is just a translator — HTTP
POST in, DNS API call out. No database. The DNS record IS the state.

Constraints:

- DNS responses have size limits. Keep 30-50 recently-alive nodes in rotation, not all.
- Liveness check before adding: ping the registering node's mesh receptor. Valid
  response? Added. No response? Ignored. Prevents fake registrations.
- Rate limiting per source IP. Possibly lightweight proof-of-work to make flooding
  expensive.

### Tier 2: Gossip-based peer exchange

Once connected to ANY peer, ask "who else do you know?" Peer list grows organically.
Within minutes a node has a rich peer list. The mesh IS its own registry after
bootstrap. No external infrastructure needed once connected.

### Tier 3: Manual introduction

A friend gives you their node address. You add it. Zero infrastructure dependency.
Works if literally everything else is down.

### Tier 4: Release-channel seeds (fallback)

If DNS is unreachable and no manual peers are configured, the TeleClaude release can
include a small list of known stable nodes as fallback. Updated with each release.

## Transport: How Peers Talk

Each TeleClaude instance already runs a daemon with an API. Today it listens on a unix
socket. The mesh receptor is an HTTPS endpoint on the daemon — a specific route that
receives events from peers.

Peer A sends an event to Peer B: HTTP POST to B's mesh receptor with the event
envelope as payload. B's hook system receives it, routes it to the internal notification
service. Same processing path as local events. The notification service doesn't know or
care whether the event came from a local producer or a remote peer.

Authentication: signed events. Every event has a source identity. Every identity has a
keypair. The signature proves the event came from who it says it came from. Invalid
signature = dropped at the receptor. Never hits the notification service.

## Propagation: What Travels

Not every event propagates everywhere — that would be a flood. Events propagate based
on subscription interest. A node declares: "I care about `infrastructure.*` events and
`deployment.*` events." Peers know this. When they see matching events, they forward
them. Non-matching events don't travel. Each node only receives what it asked for.

Service descriptors (`service.published`) propagate through gossip. Each receiving node
decides locally whether to index them or ignore them.

## Burst Mitigation: Communication Etiquette

When mesh-wide events trigger responses from many nodes simultaneously (e.g., voting
on a PR), the burst could self-DOS the mesh. Each node has a deterministic delivery
offset based on its mesh position (geography, node ID hash, or similar). Responses
arrive as a steady stream, not a wall. Simple convention, no infrastructure needed.

## Relationship to Existing Infrastructure

- The hook system IS the receptor. Hooks already receive and route signals internally.
  Pointing hooks outward (receiving from peers) requires no architectural change.
- `telec computers list` already knows about remote machines. Peer discovery extends
  this naturally.
- Every TeleClaude instance IS already a git clone. It already pulls updates on its
  release channel. The mesh adds runtime connectivity on top of the existing
  distribution mechanism.
- Redis Streams remain the internal event bus within each node. The mesh is the
  inter-node transport. They connect through the hook/receptor boundary.

## Dependencies

- event-platform (the internal event processing that mesh events feed into)
- event-envelope-schema (the format of what travels between nodes)
- mesh-trust-model (how received events are evaluated)
