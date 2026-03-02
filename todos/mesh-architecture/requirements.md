# Requirements: mesh-architecture

## Goal

Deploy a P2P mesh layer on top of the existing daemon. Every TeleClaude instance
becomes a node: it discovers peers, exchanges event subscriptions, and forwards events
matching peer interests over HTTPS. The internal event processing (Redis Streams pipeline)
remains unchanged — the mesh is the inter-node transport that feeds into the existing
hook/receptor boundary.

This todo defines the canonical node identity format, keypair lifecycle, receptor endpoint
contract, DNS record schema, peer list persistence, subscription protocol, and burst
mitigation strategy. All dependent todos (`mesh-trust-model`, `event-mesh-distribution`,
`community-governance`) block on these definitions being stable.

Initial delivery scope is **local cluster** (computers already known to each other via
Redis transport). Public mesh (internet-facing P2P) is explicitly out of scope for this
phase.

## Scope

### In scope

1. **Node identity format** — canonical specification of what constitutes a mesh node's
   identity string. Used as the `source` field in `EventEnvelope`, as the primary key in
   the trust ring (`peer_id`), and in all gossip messages.
2. **Keypair lifecycle** — generation, storage, access controls, rotation policy.
3. **Network bootstrap** — four-tier discovery sequence.
4. **Mesh receptor endpoint** — HTTPS POST path, request schema, response codes.
5. **DNS record schema** — TXT/SRV wire format for the Cloudflare Worker translator.
6. **Subscription declaration protocol** — how a node registers event type interests
   with discovered peers.
7. **Peer list persistence** — file-backed peer list, location, format, reload behavior.
8. **Burst mitigation** — deterministic delivery offset algorithm.
9. **Integration with `telec computers list`** — mesh peers appear as known computers.
10. **Local cluster scope only** — nodes already sharing a Redis instance. Public mesh deferred.

### Out of scope

- P2P transport for internet-facing nodes (public mesh — future phase).
- Trust ring evaluation and scoring (→ `mesh-trust-model`).
- Event forwarding logic and visibility routing (→ `event-mesh-distribution`).
- Community governance, voting, service publication (→ later todos blocked on this one).
- Cloudflare Worker implementation (infrastructure, not daemon code).
- Key revocation and certificate authority (deferred to public mesh phase).

## Node Identity Format

A mesh node's canonical identity is a **32-character lowercase hex string** derived
from the SHA-256 fingerprint of its Ed25519 public key, truncated to the first 16 bytes:

```
node_id = sha256(public_key_bytes)[:16].hex()
# Example: "a3f2c1e8b74d0591"
```

This value is the `source` field in every `EventEnvelope` emitted by this node. It is
the primary key in the trust ring database (`peer_id TEXT PRIMARY KEY`). It is stable
across restarts and unique with overwhelming probability. A human-readable alias
(`config.node.name`) may accompany it in gossip messages but is not used as an identifier.

`EventEnvelope.source` must always be a valid node_id for mesh-originated events.
Events emitted by local producers before mesh initialization use the empty string or the
node_id once available — the identity module initializes before the pipeline starts.

## Keypair Lifecycle

### Storage location

```
~/.teleclaude/identity/
  ├── node.key          # Ed25519 private key, PEM format, mode 0600
  ├── node.pub          # Ed25519 public key, PEM format, mode 0644
  └── node.id           # node_id hex string (32 chars), plain text, mode 0644
```

The `identity/` directory is created by `telec init` and must not be created by the
daemon at runtime.

### Generation

On `telec init`, if `~/.teleclaude/identity/node.key` does not exist:

1. Generate a new Ed25519 keypair (`cryptography` library, `Ed25519PrivateKey.generate()`).
2. Write private key to `node.key` in PEM format with mode 0600.
3. Write public key to `node.pub` in PEM format with mode 0644.
4. Derive `node_id` and write to `node.id` with mode 0644.

If `node.key` already exists, do nothing — never overwrite on init.

### Rotation policy

- Manual rotation only. Run `telec identity rotate` (not part of this todo; add to backlog).
- Rotation generates a new keypair, writes it, and broadcasts a `node.key_rotated` event
  to known peers with the old identity as proof of transition. Trust ring migration is
  handled by `mesh-trust-model`.
- Automatic rotation is out of scope for the local cluster phase.

### Access

The daemon reads `node.key` once at startup and holds the signing key in memory. It does
not re-read from disk at runtime. If the file is absent or unreadable, the daemon logs an
error and disables mesh functionality (pipeline continues without mesh). `node.pub` and
`node.id` are read-only at runtime — they can be served over the receptor to peers who
request identity verification.

## Network Bootstrap (4-Tier)

Tiers are tried in order on daemon startup, then repeated on a configurable interval
(default: 10 minutes) for peer list refresh. Each tier is independent — failure in one
does not prevent attempting the next.

### Tier 1: DNS-based discovery

Query `TXT _mesh._tcp.instrukt.ai` (or configured override). The record contains a
newline-separated list of `{node_id}@{host}:{port}` strings for currently-active bootstrap
peers. Parse, attempt a handshake ping to each, add responsive nodes to the peer list.

DNS record is updated by a stateless Cloudflare Worker (see DNS Record Schema below).

### Tier 2: Gossip-based peer exchange

After connecting to any peer, send a `PEERS_REQUEST` gossip message. Peer responds with
its known peer list (up to 50 entries). Merge new entries into the local peer list.
Gossip runs passively: on every new peer connection, exchange peer lists.

### Tier 3: Manual introduction

Peers added via `telec peers add {node_id}@{host}:{port}` (CLI, not part of this todo
but spec here so implementations are compatible). Written directly to the peer list file.
No handshake required at add time — connection attempted on next bootstrap cycle.

### Tier 4: Release-channel seed list

A YAML list of known stable nodes shipped in `teleclaude/mesh/seeds.yaml`. Used as last
resort when DNS is unreachable and no manual peers are configured. Updated per release.
Nodes from this list are marked as `origin: seed` in the peer list.

## Mesh Receptor Endpoint

The daemon exposes a mesh receptor on its existing HTTP API server (or a dedicated port —
TBD, but sharing the existing API server is preferred to avoid firewall complexity).

```
POST /mesh/events
Content-Type: application/json
Authorization: <see authentication below>
```

**Request body:**

```json
{
  "envelope": { /* EventEnvelope as JSON */ },
  "signature": "<base64url Ed25519 signature over canonical envelope JSON>",
  "sender_node_id": "<32-char hex>"
}
```

**Authentication:** The receptor verifies the signature before any other processing.
Canonical envelope JSON is `json.dumps(envelope_dict, sort_keys=True, separators=(',',':'))`.
Signature is produced by the sender over this canonical form using its Ed25519 private key.
If the signature is invalid or `sender_node_id` is not in the known peer list, the receptor
returns 401 and drops the event.

**Response codes:**

| Code | Meaning                                                   |
|------|-----------------------------------------------------------|
| 202  | Accepted. Event queued for pipeline ingestion.            |
| 400  | Malformed JSON or missing required fields.                |
| 401  | Invalid signature or unknown sender.                      |
| 413  | Payload too large (> 4 MB).                               |
| 429  | Rate limit exceeded (burst mitigation).                   |
| 503  | Pipeline not ready; retry with backoff.                   |

The receptor never blocks on pipeline processing — it enqueues and returns 202 immediately.

## DNS Record Schema

The Cloudflare Worker publishes a DNS TXT record at `_mesh._tcp.instrukt.ai`.

**Wire format (TXT record value):**

```
v=tcmesh1 peers=<peer1>;<peer2>;...;<peerN>
```

Where each peer entry is:

```
{node_id}@{host}:{port}
```

Example:

```
v=tcmesh1 peers=a3f2c1e8b74d0591@192.0.2.10:8443;b7e1a4c9d28f3602@mesh.example.com:8443
```

Constraints:

- Maximum 50 peer entries in rotation (DNS response size limit).
- Only nodes that passed a liveness ping within the last 60 minutes are included.
- The Cloudflare Worker accepts registration via `POST /register` with body
  `{"node_id": "...", "host": "...", "port": 8443}`. It pings the registering node's
  receptor (`GET /mesh/ping`) before adding. No response = ignored.
- Rate limit: one registration per node_id per hour.

The daemon calls `POST https://mesh.instrukt.ai/register` on startup and on the 10-minute
refresh cycle. The endpoint URL is configurable in `config.mesh.registry_url`.

## Subscription Declaration Protocol

A node declares its event type interests to peers via a `SUBSCRIBE` gossip message sent
after the initial peer handshake. Subscriptions are re-sent on reconnect and on
`SIGHUP`.

**Gossip message format (JSON, sent over mesh receptor's `/mesh/gossip` endpoint):**

```json
{
  "type": "SUBSCRIBE",
  "node_id": "<sender node_id>",
  "interests": ["domain.software-development.*", "system.daemon.*"],
  "timestamp": "<ISO8601 UTC>"
}
```

- `interests` is a list of glob patterns matched against `event_type`.
- An empty interests list means "no subscriptions" (node receives nothing from this peer).
- Subscriptions replace the previous declaration — not additive. Send the full list.
- Peers store subscriptions in memory (rebuilt on reconnect). No persistence required.

The local node's interests are configured in `config.mesh.interests` (list of glob patterns).
Default: `["*"]` (receive everything from peers — safe for local cluster phase).

## Peer List Persistence

The peer list survives daemon restarts via a file-backed store.

**Location:** `~/.teleclaude/peers.yaml`

**Format:**

```yaml
peers:
  - node_id: "a3f2c1e8b74d0591"
    host: "192.0.2.10"
    port: 8443
    alias: "mo-laptop"          # optional, from gossip
    origin: "dns"               # dns | gossip | manual | seed
    last_seen: "2026-03-01T10:00:00Z"
    last_handshake: "2026-03-01T09:55:00Z"
    status: "reachable"         # reachable | unreachable | unknown
  - node_id: "b7e1a4c9d28f3602"
    host: "mesh.example.com"
    port: 8443
    alias: null
    origin: "manual"
    last_seen: null
    last_handshake: null
    status: "unknown"
```

**Reload:** The daemon reads `peers.yaml` on startup and after `SIGHUP`. It writes
to `peers.yaml` atomically (write to `.peers.yaml.tmp`, then rename) after every peer
list change (new peer discovered, status change, last_seen update). No external tool
writes to this file — it is daemon-owned.

**Stale peer eviction:** Peers with `status: unreachable` and `last_seen` older than
30 days are evicted from the file on the next bootstrap cycle. Manual peers are never
evicted regardless of status.

## Burst Mitigation

When a mesh-wide event triggers responses from many nodes simultaneously, each node
applies a deterministic delivery offset before sending its response. This spreads the
burst across time without coordination.

**Offset formula:**

```python
import hashlib, struct

def delivery_offset_ms(node_id: str, event_id: str, max_offset_ms: int = 5000) -> int:
    digest = hashlib.sha256(f"{node_id}:{event_id}".encode()).digest()
    value = struct.unpack(">Q", digest[:8])[0]
    return value % max_offset_ms
```

- `node_id` is the local node's identity.
- `event_id` is the `EventEnvelope.event_id` (UUID) of the triggering event.
- `max_offset_ms` defaults to 5000ms (5 seconds); configurable at `config.mesh.burst_max_offset_ms`.

The pipeline executor applies this offset before calling the mesh publishing cartridge
when the event is a mesh-wide broadcast. For cluster-scoped events the offset is 0
(cluster peers are already coordinated via Redis).

## Integration with `telec computers list`

Mesh peers that complete a successful handshake are surfaced in `telec computers list`
alongside computers already known via Redis transport. Peer entries from the mesh are
annotated as `source: mesh` in the listing output.

The `PeerInfo` model must be extended with a `node_id: str | None` field to carry
the mesh identity. Computers known only via Redis have `node_id: None`. Computers
discovered via mesh have `node_id` set to their canonical 32-char hex identity.

The `telec computers list` command queries both sources: Redis-discovered peers (existing
path) and the in-memory mesh peer list (new path). Results are merged by `host`, with
mesh data augmenting Redis data when the same computer appears in both.

## Success Criteria

- [ ] `~/.teleclaude/identity/node.key`, `node.pub`, and `node.id` are created by `telec init` and survive daemon restarts unchanged.
- [ ] `node_id` is a valid 32-char lowercase hex string derived from the Ed25519 public key fingerprint.
- [ ] Daemon refuses to start mesh subsystem if `node.key` is absent; pipeline continues.
- [ ] On startup, daemon queries DNS TXT record and attempts handshake with returned peers.
- [ ] Peers discovered via gossip, DNS, manual introduction, or seed list are added to `peers.yaml`.
- [ ] `peers.yaml` is reloaded on `SIGHUP` without daemon restart.
- [ ] `POST /mesh/events` rejects events with invalid signatures (returns 401).
- [ ] `POST /mesh/events` accepts valid signed events and enqueues them for pipeline ingestion.
- [ ] A `SUBSCRIBE` gossip message is sent to each newly-connected peer.
- [ ] Events not matching peer interests are not forwarded to that peer.
- [ ] At least 2 nodes on the same local cluster can exchange events end-to-end (emit on A → pipeline on B).
- [ ] `telec computers list` shows mesh peers alongside Redis-transport peers.
- [ ] Burst offset formula produces a deterministic, bounded offset per (node_id, event_id) pair.
- [ ] `make test` passes; `make lint` passes.

## Constraints

- Ed25519 is the mandatory keypair algorithm. RSA and ECDSA are not acceptable.
- The `cryptography` library is the only permitted crypto dependency (already in the
  ecosystem; avoids introducing `PyNaCl` or similar).
- The mesh receptor shares the existing daemon HTTP port. No second port for local cluster.
- Peer list file (`peers.yaml`) is daemon-owned — no agent or CLI writes to it directly.
- Subscription interests are declared, not negotiated. No protocol round-trip for approval.
- Local cluster phase only: all peers must be reachable via LAN or existing Redis network.
  Internet-facing P2P is deferred.
- `node_id` format must be locked before `mesh-trust-model` ships. Trust ring migration
  on format change is expensive. This requirement is a hard gate for dependent todos.

## Risks

- **`PeerInfo` model extension:** Adding `node_id` to `PeerInfo` requires updating all
  sites that construct or serialize `PeerInfo`. The heartbeat/peer-broadcast mechanism in
  `redis_transport.py` is the primary impact area. Audit required before implementation.
- **DNS TTL lag:** DNS records are cached. A newly registered node may not appear in peer
  lists for minutes. Acceptable for bootstrap — not for real-time peer discovery.
  Gossip handles real-time; DNS is only bootstrap.
- **Receptor on shared port:** If the existing API server uses a unix socket, the mesh
  receptor needs a TCP binding. Requires a daemon config option for a TCP listener.
  Confirm current binding before implementation.
- **Key format lock-in:** Once the `node_id` derivation formula is adopted and the trust
  ring is populated, changing it requires a migration. Define carefully and test
  round-trip fidelity before shipping `mesh-trust-model`.
- **Peer list growth:** Gossip exchange can rapidly expand the peer list. Cap at 500
  entries (evicting oldest `last_seen` beyond that). Not a concern for local cluster
  phase but required before public mesh.
