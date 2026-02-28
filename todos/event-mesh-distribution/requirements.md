# Requirements: event-mesh-distribution

## Goal

Activate the `visibility` field on the event envelope: route `cluster` events to all
computers in the owner's cluster via Redis transport, and route `public` events to
all discovered peers. Incoming mesh events pass through the local trust evaluator
before entering the pipeline. Add cartridge publishing as a specialized public event
with sovereignty-gated installation on receiving nodes.

## Scope

### In scope

1. **Mesh publishing cartridge** (`teleclaude_events/cartridges/mesh_publisher.py`):
   - Registered in the system pipeline after the notification projector.
   - Inspects `event.visibility` on every outbound event.
   - `visibility: cluster` → XADD to `messages:{peer_computer}` for each computer in
     the owner's cluster (uses existing `RedisTransport.discover_peers()` + cluster
     membership check).
   - `visibility: public` → XADD to `messages:{peer_computer}` for every discovered peer.
   - `visibility: local` → no-op (pass through unchanged).
   - Message envelope wrapper: `{"type": "mesh_event", "payload": <event JSON>}` in the
     existing `messages:{computer}` stream format.

2. **Cluster membership logic** (`teleclaude_events/mesh/cluster.py`):
   - `get_cluster_peers(transport: RedisTransport) -> list[PeerInfo]`: returns peers
     sharing the same cluster affiliation as the local computer.
   - Cluster affiliation read from `config.computer.cluster` (existing config field or
     new field — confirm from codebase).
   - `get_all_peers(transport: RedisTransport) -> list[PeerInfo]`: returns all discovered
     peers excluding self.

3. **Mesh ingress handler** (`teleclaude_events/mesh/ingress.py`):
   - Registered as a handler for `type: mesh_event` messages arriving on the
     `messages:{computer_name}` stream (hooked into `RedisTransport` message dispatch).
   - Deserializes the nested `EventEnvelope` from the payload.
   - Stamps envelope with `source_computer` for provenance.
   - Passes envelope to the trust evaluator cartridge first (no bypassing the trust gate).
   - If trust passes: feeds the envelope into the local `EventProcessor` pipeline.
   - If trust fails: emits a local `mesh.event.rejected` event (level: OPERATIONAL).

4. **Trust evaluator integration**:
   - Mesh ingress explicitly invokes the trust cartridge (`event-system-cartridges` phase)
     before entering the main pipeline.
   - If `event-system-cartridges` is not yet available, ingress uses a stub that accepts
     all events from known cluster peers and rejects unknown sources.
   - Stub lives in `teleclaude_events/mesh/trust_stub.py`; replaced by real cartridge
     when that phase lands.

5. **Cartridge publishing event** (`teleclaude_events/schemas/cartridges.py`):
   - `cartridge.published` schema: event_type, version, author, code payload (base64 UTF-8
     source), entry_point (callable path), dependencies (list[str]), description.
   - Default visibility: `public`.
   - Default level: WORKFLOW.
   - Idempotency fields: `[author, event_type, version]`.

6. **Sovereignty-gated installation** (`teleclaude_events/mesh/installer.py`):
   - `CartridgeInstaller` class: receives `cartridge.published` events from the pipeline.
   - Reads `config.autonomy.cartridge_install` (global default: L1).
   - L1 (human approves): create a `cartridge.install_pending` notification (actionable);
     human approves via `POST /api/notifications/{id}/resolve`.
   - L2 (AI decides, human notified): guardian AI evaluates; if approved, install and emit
     `cartridge.installed`; also emit `cartridge.install_notified` to human.
   - L3 (fully autonomous): install immediately, emit `cartridge.installed`.
   - Installation = write cartridge source to `~/.teleclaude/cartridges/incoming/{name}.py`,
     register in the event catalog with `status: pending_activation`.
   - Activation = separate human step: `telec cartridges activate {name}`.

7. **Organic promotion tracking** (`teleclaude_events/mesh/promotion.py`):
   - `CartridgePromotionTracker` cartridge: observes `cartridge.invoked` meta-events.
   - Maintains invocation counts per cartridge in `events.db` (`cartridge_stats` table).
   - When invocation count crosses configurable threshold (default: 10), emits
     `cartridge.promotion_suggested` event (level: WORKFLOW, actionable: true).
   - `cartridge.invoked` emitted automatically by the pipeline executor after each
     successful cartridge run.

8. **New event schemas** (`teleclaude_events/schemas/cartridges.py`):
   - `cartridge.published` — code-as-data payload, visibility: public
   - `cartridge.install_pending` — actionable, lifecycle: creates notification
   - `cartridge.install_notified` — lifecycle: creates notification (informational)
   - `cartridge.installed` — lifecycle: creates notification
   - `cartridge.invoked` — level: INFRASTRUCTURE, no lifecycle (high-volume, stats only)
   - `cartridge.promotion_suggested` — actionable, lifecycle: creates notification
   - `mesh.event.rejected` — level: OPERATIONAL, lifecycle: creates notification

9. **Autonomy config extension** (`teleclaude/config.py` or equivalent):
   - `config.autonomy.cartridge_install: "L1" | "L2" | "L3"` (default: L1)
   - `config.computer.cluster: str | None` (cluster affiliation identifier)

10. **`telec cartridges` CLI subcommand** (new):
    - `telec cartridges list` — shows installed cartridges with status and invocation count
    - `telec cartridges activate {name}` — moves pending cartridge into active pipeline
    - `telec cartridges reject {name}` — removes a pending cartridge

11. **Daemon wiring**:
    - `MeshPublishingCartridge` added to system pipeline after notification projector.
    - `CartridgeInstaller` registered as a pipeline push callback.
    - `CartridgePromotionTracker` added to the pipeline after `MeshPublishingCartridge`.
    - Mesh ingress handler registered in `RedisTransport` message dispatch.

12. **`cartridge_stats` table migration** in `teleclaude_events/db.py`:
    - `cartridge_name TEXT`, `invocation_count INTEGER`, `last_invoked_at TEXT`.
    - `UNIQUE(cartridge_name)`.

### Out of scope

- P2P transport infrastructure (→ `mesh-architecture`)
- Domain-scoped cartridge management and guardian AI (→ `event-domain-infrastructure`)
- Alpha container sandboxing (→ `event-alpha-container`)
- Community governance UI and voting (→ `community-governance`)
- Community manager agent (→ `community-manager-agent`)
- Cartridge signature verification / cryptographic trust
- Remote cartridge repository / registry service
- `telec://` URI scheme

## Success Criteria

- [ ] `visibility: local` events are not forwarded to any peer
- [ ] `visibility: cluster` events are forwarded exactly to cluster peers via `messages:{computer}` stream
- [ ] `visibility: public` events are forwarded to all discovered peers
- [ ] Incoming mesh events are processed through trust gate before entering local pipeline
- [ ] Mesh events from unknown sources are rejected with a `mesh.event.rejected` local event
- [ ] A `cartridge.published` event forwarded from a peer triggers the sovereignty gate
- [ ] L1 gate creates an actionable `cartridge.install_pending` notification; install completes only after human resolves
- [ ] L3 gate installs cartridge immediately without human interaction
- [ ] `cartridge.invoked` is emitted after each successful cartridge execution
- [ ] After threshold invocations, `cartridge.promotion_suggested` is emitted
- [ ] `telec cartridges list` shows installed cartridges with invocation count
- [ ] `telec cartridges activate {name}` moves a pending cartridge into the active pipeline
- [ ] `make test` passes; `make lint` passes
- [ ] No events forwarded to self (own computer excluded from peer list)

## Constraints

- Mesh transport: uses existing `messages:{computer}` Redis Streams infrastructure from
  `RedisTransport`. No new brokers or protocols.
- Trust gate is not optional for mesh ingress — every incoming external event passes through it.
- The stub trust implementation must be replaced by the real trust cartridge when
  `event-system-cartridges` is available; a `TODO` comment marks the integration point.
- Cartridge source code stored as UTF-8 text; base64 encoding only for wire transport.
- L1 is the default sovereignty level — the system is conservative by default.
- `cartridge.invoked` events are not forwarded (visibility: local) — invocation counts
  are per-node, not globally aggregated.
- Depends on `mesh-architecture` being available for peer discovery. The `MeshPublishingCartridge`
  must degrade gracefully (log warning, skip forwarding) if `RedisTransport` is not
  configured or peer discovery fails.

## Risks

- **`mesh-architecture` dependency**: if P2P transport is not ready, forwarding cannot be
  wired. Mitigate: implement the cartridges and ingress handler against the existing
  `messages:{computer}` pattern (already proven); the dependency is on peer discovery
  infrastructure, not a new transport protocol.
- **Trust stub accuracy**: the stub (accept cluster peers, reject unknown) may be too
  permissive or too restrictive depending on deployment. Mitigate: make threshold
  configurable; document as provisional.
- **High-volume `cartridge.invoked` events**: every cartridge execution emits an event.
  On active pipelines this can be high-frequency. Mitigate: `cartridge.invoked` is
  visibility: local, level: INFRASTRUCTURE — never forwarded, not notification-worthy,
  pipeline passes through. Stats are written directly to `cartridge_stats` table in the
  promotion tracker, not via the full pipeline projection path.
- **Cartridge activation safety**: installed but unactivated cartridges sit in
  `~/.teleclaude/cartridges/incoming/` indefinitely. Mitigate: `telec cartridges list`
  surfaces pending items; pending notifications are actionable.
