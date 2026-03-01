# Requirements: mesh-trust-model

## Goal

Implement per-event trust evaluation for the TeleClaude event platform using an immune
system model. Every event received from mesh peers is evaluated locally — trust is never
a property of nodes, never propagates, and never exists "on the network." The trust
evaluator is a pipeline cartridge that gates mesh-origin events before they reach
notification projection.

## Scope

### In scope

1. **TrustEvaluator cartridge** — A pipeline cartridge positioned after dedup and before
   notification. Evaluates every event with `visibility != local` against local trust
   signals. Produces a `TrustVerdict` (accept, attenuate, drop) that determines
   whether the event continues through the pipeline. Local events bypass evaluation.

2. **Trust signal computation** — Per-event evaluation based on:
   - Source identity validity (signature verification stub — real crypto comes from
     `mesh-architecture`; this todo provides the evaluation interface).
   - Source history (local observations of the source's past behavior).
   - Event content anomaly (structural checks: unexpected fields, oversized payloads,
     event types the source hasn't sent before).
   - Peer observations (trust-related events from other peers, weighted by the
     local trust opinion of the observer).

3. **Trust ring storage** — SQLite table for local peer trust records. Each record
   tracks: peer identity, trust level (unknown/observed/trusted/muted), first seen,
   last seen, interaction count, flag count, manual overrides. Trust rings are purely
   local — never serialized to the mesh.

4. **Sovereignty configuration** — YAML config surface under `trust:` in the TeleClaude
   config. Per-domain and per-event-type rules:
   - Sovereignty level per domain: `L1` (human-in-loop), `L2` (operational autonomy),
     `L3` (full autonomy). Default: `L1`.
   - Per-event-type accept/attenuate/drop overrides.
   - Global mute list (source identities to always drop).
   - Global trust list (source identities to always accept without full evaluation).

5. **Observation events** — Trust-related events emitted locally when the evaluator
   acts:
   - `trust.flagged` — a source was flagged as suspicious (with reason).
   - `trust.muted` — a source was muted (death by loneliness).
   - `trust.ring.added` — a peer was added to the trust ring.
   - `trust.ring.removed` — a peer was removed from the trust ring.
   These are local-visibility events processed by the existing pipeline.

6. **Trust ring management API** — Daemon API endpoints for managing trust rings:
   - `GET /api/trust/ring` — list trust ring members.
   - `PUT /api/trust/ring/{peer_id}` — add/update a peer's trust level.
   - `DELETE /api/trust/ring/{peer_id}` — remove a peer from the ring.
   - `GET /api/trust/history/{peer_id}` — view local observation history for a peer.

7. **Pipeline integration** — Register the TrustEvaluator in the pipeline cartridge
   chain. The evaluator reads trust ring data and sovereignty config at startup and
   watches for config changes.

### Out of scope

- Cryptographic signature verification implementation (that's `mesh-architecture`).
  This todo provides the interface the evaluator calls; the real implementation is
  wired when mesh-architecture lands.
- Mesh transport and peer discovery (that's `mesh-architecture`).
- Event envelope schema changes (that's `event-envelope-schema`). The trust evaluator
  reads existing envelope fields; it does not add new fields to the wire format.
- AI-driven trust inference (future work — the evaluator uses rule-based signals).
- Cross-node trust synchronization (violates "trust never travels" principle).
- Sovereignty level enforcement beyond event gating (L1/L2/L3 behavioral differences
  are future domain pipeline work).

## Success Criteria

- [ ] TrustEvaluator cartridge processes events and produces accept/attenuate/drop
      verdicts based on source identity, history, and sovereignty config.
- [ ] Local-origin events (`visibility == local`) bypass trust evaluation entirely.
- [ ] Trust ring records persist in SQLite across daemon restarts.
- [ ] Sovereignty config is read from YAML and applied per-domain/per-event-type.
- [ ] Muted sources are dropped immediately without further evaluation.
- [ ] Trusted ring members receive streamlined evaluation (accept fast path).
- [ ] Observation events (`trust.flagged`, `trust.muted`, `trust.ring.*`) are emitted
      for local pipeline consumption.
- [ ] Trust ring management API endpoints work and validate inputs.
- [ ] Existing local event processing is unaffected (zero regression).
- [ ] Tests cover: accept, attenuate, drop paths; trust ring CRUD; sovereignty config
      parsing; mute/trust list behavior; local event bypass.

## Constraints

- The trust evaluator must not block the pipeline for longer than 10ms per event
  under normal conditions. SQLite lookups are fast; keep the evaluation synchronous
  within an async cartridge.
- Trust ring storage uses the daemon's existing SQLite database (per single-database
  policy). New tables, same file.
- Config surface follows existing TeleClaude YAML config patterns. No new config file
  formats.
- The cartridge protocol requires `async def process(event, context) -> EventEnvelope | None`.
  The evaluator must conform — returning `None` to drop, the event to accept, or
  a modified event (with attenuated visibility) to attenuate.
- Signature verification is a stub interface (`SignatureVerifier` protocol) that
  returns `valid | invalid | unverifiable`. The stub always returns `unverifiable`
  until `mesh-architecture` provides the real implementation.

## Risks

- **Dependency timing**: `event-envelope-schema` and `mesh-architecture` are not yet
  built. Mitigation: design against the current `EventEnvelope` model and define
  clear interfaces (SignatureVerifier protocol) for future wiring. The evaluator
  works with current envelopes and gracefully handles the `unverifiable` signature
  state.
- **Performance under load**: If the mesh delivers many events per second, per-event
  SQLite lookups could become a bottleneck. Mitigation: cache trust ring data in
  memory with periodic refresh. SQLite is the persistence layer, not the hot path.
- **Config complexity**: Sovereignty config per-domain × per-event-type can get
  complex. Mitigation: simple defaults (L1 everywhere), explicit overrides only
  where needed. Config validation at startup catches errors early.
