# Implementation Plan: mesh-trust-model

## Overview

Build the trust evaluation layer as a pipeline cartridge with SQLite-backed trust ring
storage and YAML-driven sovereignty configuration. The approach follows the existing
cartridge pattern (dedup, notification) and integrates into the same pipeline chain.
New code lives in `teleclaude_events/trust/` to keep the trust domain self-contained.

## Phase 1: Trust Data Layer

### Task 1.1: Trust ring SQLite schema

**File(s):** `teleclaude_events/trust/db.py`

- [ ] Create `trust_peers` table: `peer_id TEXT PRIMARY KEY`, `trust_level TEXT`
      (unknown/observed/trusted/muted), `first_seen TEXT`, `last_seen TEXT`,
      `interaction_count INTEGER`, `flag_count INTEGER`, `manual_override INTEGER`,
      `notes TEXT`, `created_at TEXT`, `updated_at TEXT`.
- [ ] Create `trust_observations` table: `id INTEGER PRIMARY KEY`, `peer_id TEXT`,
      `event_type TEXT`, `observation TEXT` (flagged/anomaly/normal), `reason TEXT`,
      `created_at TEXT`. Index on `peer_id` and `created_at`.
- [ ] Implement `TrustDB` class with `init()` that creates tables in the daemon's
      existing SQLite database (reuse connection pattern from `EventDB`).
- [ ] CRUD methods: `get_peer`, `upsert_peer`, `remove_peer`, `list_ring` (trusted
      peers), `list_all_peers`, `add_observation`, `get_observations`.
- [ ] In-memory cache: `TrustRingCache` that loads trust ring + muted peers into
      a `dict[str, TrustLevel]` at startup with periodic refresh (configurable
      interval, default 30s).

### Task 1.2: Sovereignty config model

**File(s):** `teleclaude_events/trust/config.py`

- [ ] Define `SovereigntyLevel` enum: `L1` (human-in-loop), `L2` (operational),
      `L3` (full autonomy).
- [ ] Define `TrustConfig` Pydantic model:
      - `default_sovereignty: SovereigntyLevel = L1`
      - `domain_sovereignty: dict[str, SovereigntyLevel] = {}`
      - `event_overrides: dict[str, str] = {}` (event pattern → accept/attenuate/drop)
      - `mute_list: list[str] = []`
      - `trust_list: list[str] = []`
      - `cache_refresh_seconds: int = 30`
- [ ] Config loader that reads `trust:` section from TeleClaude YAML config.
      Returns `TrustConfig` with defaults if section is missing.

### Task 1.3: Trust verdict model

**File(s):** `teleclaude_events/trust/verdict.py`

- [ ] Define `TrustVerdict` enum: `ACCEPT`, `ATTENUATE`, `DROP`.
- [ ] Define `TrustEvaluation` dataclass: `verdict`, `reason: str`,
      `source_trust_level: str`, `signals: list[str]`.
- [ ] Define `SignatureVerifier` protocol: `async def verify(source: str, event: EventEnvelope) -> str`
      returning `valid`, `invalid`, or `unverifiable`.
- [ ] Implement `StubSignatureVerifier` that always returns `unverifiable`.

---

## Phase 2: Trust Evaluator Cartridge

### Task 2.1: Core evaluation logic

**File(s):** `teleclaude_events/trust/evaluator.py`

- [ ] Implement `TrustEvaluator` class conforming to the `Cartridge` protocol.
- [ ] `__init__` accepts `TrustDB`, `TrustRingCache`, `TrustConfig`,
      `SignatureVerifier`.
- [ ] `process(event, context)` logic:
      1. If `event.visibility == EventVisibility.LOCAL`: return event (bypass).
      2. Check mute list: if `event.source` in mute list → drop, emit
         `trust.muted` observation.
      3. Check trust list: if `event.source` in trust list → accept fast path.
      4. Check event overrides: if event type matches an override → apply directly.
      5. Verify signature (via `SignatureVerifier` protocol).
         `invalid` → drop. `unverifiable` → continue with penalty signal.
      6. Look up source in trust ring cache:
         - `trusted`: accept with streamlined evaluation.
         - `observed`: evaluate signals, accept or attenuate.
         - `unknown`: evaluate signals, accept/attenuate/drop.
         - `muted`: drop (should not reach here due to step 2, defensive).
      7. Evaluate content signals: unexpected event types from source, oversized
         payload (>64KB), structural anomalies.
      8. Check peer observations: if other trusted peers flagged this source,
         weight their observations.
      9. Combine signals into final `TrustEvaluation`. Map to verdict.
      10. Record observation in `TrustDB`. Update `last_seen` and
          `interaction_count`.
      11. Return: `None` (drop), event (accept), or event with `visibility`
          downgraded to `LOCAL` (attenuate).
- [ ] Emit observation events via `context.push_callbacks` for trust actions.

### Task 2.2: Observation event schemas

**File(s):** `teleclaude_events/schemas/trust.py`, `teleclaude_events/trust/events.py`

- [ ] Register trust event schemas in the catalog:
      `trust.flagged`, `trust.muted`, `trust.ring.added`, `trust.ring.removed`.
      All with `visibility: local`, `level: OPERATIONAL`, `domain: trust`.
- [ ] Helper functions to create trust observation envelopes from evaluation results.

### Task 2.3: Pipeline registration

**File(s):** `teleclaude_events/trust/__init__.py`, pipeline wiring location

- [ ] Export `TrustEvaluator`, `TrustDB`, `TrustRingCache`, `TrustConfig`.
- [ ] Register the cartridge in the pipeline chain: dedup → **trust** → notification.
- [ ] Wire `TrustDB` initialization into the daemon startup (alongside `EventDB`).
- [ ] Wire `TrustConfig` loading from the daemon config.
- [ ] Wire `StubSignatureVerifier` as default (replaced when `mesh-architecture` lands).

---

## Phase 3: Trust Ring Management API

### Task 3.1: API endpoints

**File(s):** `teleclaude/api/trust.py` (or appropriate API module location)

- [ ] `GET /api/trust/ring` — list trust ring members with trust levels.
- [ ] `PUT /api/trust/ring/{peer_id}` — add or update a peer's trust level.
      Validate `trust_level` against allowed values. Set `manual_override = true`.
- [ ] `DELETE /api/trust/ring/{peer_id}` — remove a peer. Emit `trust.ring.removed`.
- [ ] `GET /api/trust/history/{peer_id}` — list observations for a peer,
      paginated (default 50, max 200).
- [ ] Register routes with the daemon API server.

### Task 3.2: Config surface documentation

**File(s):** YAML config documentation, event vocabulary doc

- [ ] Document the `trust:` config section shape and defaults.
- [ ] Add trust event families to `docs/project/spec/event-vocabulary.md`.

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Unit tests for `TrustDB`: CRUD operations, observation recording, cache
      refresh behavior.
- [ ] Unit tests for `TrustEvaluator`: all verdict paths (accept, attenuate, drop),
      local bypass, mute list, trust list, event overrides, signature states,
      content anomaly detection.
- [ ] Unit tests for `TrustConfig`: parsing, defaults, validation.
- [ ] Integration test: event flows through pipeline with trust evaluator in chain.
      Local event passes through. Mesh event from unknown source is evaluated.
      Muted source is dropped.
- [ ] API tests: trust ring CRUD via HTTP endpoints.
- [ ] Run `make test`.

### Task 4.2: Quality Checks

- [ ] Run `make lint`.
- [ ] Verify no unchecked implementation tasks remain.
- [ ] Verify existing tests pass (zero regression from cartridge insertion).

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes.
- [ ] Confirm implementation tasks are all marked `[x]`.
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable).
