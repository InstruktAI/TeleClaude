# Requirements: state-machine-versioning

## Goal

Replace the bag-of-fields `state.yaml` with a versioned state machine where the
current state is a single authoritative value, transitions are atomic and guarded,
and history enables rewind. Eliminate all inference-based state derivation,
field-by-field patching, ghost artifact protection hacks, and mark-* command
proliferation. Migrate all consumers in one pass — no hybrid intermediate state.

## Scope

### In scope

- State machine engine: states, transitions, guards, actions, idempotent semantics
- Versioned transition history with rewind capability
- New `telec todo state` CLI command surface
- Schema versioning with v1 → v2 on-read migration
- API route for `POST /todos/state` (inspection, transition firing, rewind)
- Prepare router reads `current` instead of inferring from `prepare_phase` + `_derive_prepare_phase`
- `is_ready_for_work` reads `current` instead of multi-field inference
- Work machine (Phase B) dispatch reads `current` and fires transitions
- Mark-* command consolidation into transition wrappers
- Ghost artifact protection removal (`produced_at` as state proxy eliminated)
- Pydantic model updates (`TodoState` in `types/todos.py` reflects v2 schema)
- DTO/API model updates (`api_models.py` maps from v2 fields)
- Display layer updates (`roadmap.py`, `todo_row.py`, `output_formatting.py` read `current`)
- Resource validation updates (`resource_validation/__init__.py` uses `current`)
- Agent artifact/procedure/CLI help text migration from mark-* to `telec todo state`
- NFR-1 enforcement: no code path infers lifecycle state from artifacts, digests, or field combos

### Out of scope

- Integration machine (Phase C): uses its own `IntegrationCheckpoint` +
  `IntegrationPhase` + step functions system, not `state.yaml`. Does not suffer
  from inference, ghost artifact, or field-patching problems. Unification with the
  generic engine is a consistency improvement, not a correctness fix — separate todo
  if desired.
- Roadmap.yaml structure changes (item metadata, not lifecycle state)
- DOR scoring algorithm changes (gate check, not state transition)
- Creative lifecycle state machines (separate domain)
- Changes to artifact file formats (`.md` files themselves)

## Functional Requirements

### FR-1: Authoritative State Value

The state machine maintains a single `current` field as the sole source of truth
for lifecycle phase.

**Success criteria:**

- `next_prepare()` reads `state["current"]` and maps to `PreparePhase` directly
- The `_derive_prepare_phase` fallback path is removed
- `is_ready_for_work()` checks `state["current"]` instead of multi-field inference
- `_apply_stale_artifact_reroute` and prepare routing read/write `current`
- `next_work()` precondition checks read `state["current"]`
- No code path infers current state from artifact existence, file digests, or field combinations

### FR-2: Atomic Guarded Transitions

State changes happen through named transitions with precondition guards. A
transition either succeeds atomically (state + history updated together) or
fails with a typed rejection.

**Success criteria:**

- Each transition declares source state(s) and target state
- Guards validate preconditions before the transition fires
- Guard failure leaves state unchanged; caller receives `TransitionRejected` with diagnostic
- No partial state updates are possible through the engine

### FR-3: Idempotent Transition Semantics

Transitions follow idempotency rules:

- Already past the target state → no-op (success, no state change, action not re-executed)
- At the required source state → fires the transition
- Not yet at the required source state → rejects with diagnostic

**Success criteria:**

- Idempotency is built into the engine, not per-transition custom logic
- The "past" check uses the ordered states list for index comparison

### FR-4: Versioned Transition History

Every transition appends a history entry capturing transition metadata.

**Success criteria:**

- History entries include: source state, target state, transition name,
  timestamp, actor identity (session ID), and transition-specific metadata
  (e.g., verdict value, digest)
- History is append-only during normal operation
- History survives YAML serialization round-trips

### FR-5: Rewind Capability

The state machine supports reverting to the previous state by popping the most
recent history entry.

**Success criteria:**

- `StateMachine.rewind(snapshot)` restores the previous state from history
- Rewind on empty history raises `RewindRejected` with the current state
- `telec todo state <slug> --rewind` exposes rewind through the CLI

### FR-6: Steps as Functions

Transition behavior is defined as Python callables, not external configuration.

**Success criteria:**

- `TransitionDefinition` accepts optional `action` and `guard` callables
- The engine executes transitions through one consistent callable contract
- Adding a new transition requires only code, not configuration

### FR-7: CLI Command Surface

A new `telec todo state` command provides state inspection and transition firing.

**Success criteria:**

- `telec todo state <slug>` displays current state, history, and valid transitions
- `telec todo state <slug> <transition>` fires a named transition (idempotent)
- `telec todo state <slug> --rewind` pops to the previous state
- Surface definition added to `CLI_SURFACE` dict with appropriate auth

### FR-8: Schema Versioning and Migration

The v2 state blob carries `schema_version: 2`. On-read migration converts v1
bag-of-fields to v2 format.

**Success criteria:**

- `read_phase_state()` detects `schema_version: 1` (or absent) and migrates to v2
- Migration derives `current` from existing field combination
  (`prepare_phase`, `build`, `review`, `finalize.status`)
- Legacy top-level fields (`prepare_phase`, `build`, `review`) are removed from migrated blob
- V2 blobs skip deep-merge with `default_state()` (they are self-contained)
- Migration is idempotent: reading a v2 file does not re-migrate
- The migration helper is reusable for future version transitions

### FR-9: Mark-* Command Consolidation

The existing `mark_phase`, `mark_prepare_phase`, `mark_ready`, and
`mark_finalize_ready` functions become thin wrappers that fire corresponding
transitions through the `StateMachine` engine.

**Success criteria:**

- Each mark-* function reads v2 state, fires the appropriate transition, writes result
- CLI surface and API routes for mark-* continue to work (backward compatibility)
- Wrappers produce the same observable state changes as current implementations

### FR-10: Ghost Artifact Protection Removal

The `produced_at` existence checks in `prepare_events.py` used as state proxy
are eliminated. State authority comes from `current`.

**Success criteria:**

- `_is_artifact_produced()` checks removed or replaced with `current`-based state checks
- No code path uses artifact metadata (`produced_at`, `digest`) as proxy for lifecycle phase

### FR-11: Consumer Model Updates

All remaining consumers of the legacy field model switch to v2 format.

**Success criteria:**

- `TodoState` Pydantic model in `types/todos.py` replaces `build`, `review`,
  `prepare_phase` top-level fields with `current` and `history`
- `TodoDTO`/`TodoInfo` in `api_models.py` maps from v2 fields
- `roadmap.py` reads `current` instead of `build`/`review`
- `resource_validation/__init__.py` checks `current` instead of `build`
- `todo_row.py` TUI widget reads `current` for display
- `output_formatting.py` guidance strings reference `telec todo state`

### FR-12: Work Machine Transition Adoption

The work machine dispatch reads `current` and fires transitions instead of
calling `mark_phase()` directly.

**Success criteria:**

- Build/review status advancement uses `StateMachine.fire()`
- `_mark_finalize_handed_off()` routes through the transition engine
- No direct field writes for lifecycle state remain in `work.py`

## Non-Functional Requirements

### NFR-1: No Inference Anywhere

After delivery, no code path in the codebase infers lifecycle state from artifact
existence, file digests, field combinations, or checkpoint-specific state
reconstruction (excluding the integration module which has its own system).

**Success criteria:**

- Grep sweep confirms no remaining references to `prepare_phase`,
  `state["build"]`, or `state["review"]` as state authority outside migration
  code and test characterization
- `_derive_prepare_phase` is deleted or unreachable from runtime paths

### NFR-2: Atomic Writes

State writes remain atomic (YAML dump to file). The new `write_transition`
helper writes v2 snapshots without injecting legacy fields.

## Acceptance Criteria

- [ ] `StateMachine` engine passes all engine spec tests
- [ ] `read_phase_state()` migrates v1 state to v2 on read
- [ ] `read_phase_state()` returns v2 blobs without legacy field reintroduction
- [ ] `next_prepare()` routes from `current`, not `prepare_phase` + inference
- [ ] `is_ready_for_work()` uses `current` instead of multi-field checks
- [ ] `next_work()` dispatch reads `current` and fires transitions
- [ ] All mark-* functions route through `StateMachine.fire()`
- [ ] Ghost artifact protection (`produced_at` state proxy) removed
- [ ] `TodoState` model reflects v2 schema
- [ ] `api_models.py` maps from v2 fields
- [ ] `roadmap.py`, `todo_row.py`, `output_formatting.py` read `current`
- [ ] `resource_validation` uses `current`
- [ ] `telec todo state <slug>` shows current state and valid transitions
- [ ] `telec todo state <slug> <transition>` fires a transition
- [ ] `telec todo state <slug> --rewind` restores previous state
- [ ] API route `POST /todos/state` handles inspection, transition, and rewind
- [ ] No codebase path infers state from fields/artifacts (NFR-1)
- [ ] Agent artifacts and help text reference `telec todo state`
- [ ] Pre-commit hooks pass (lint, typecheck, tests)

## Dependencies

- No blocking dependencies.

## Constraints

- Must not break running orchestrator sessions: legacy state migrates on read
- Mark-* commands remain as wrappers during transition (not deleted yet)
- The engine is pure (no I/O, no filesystem) — persistence is the caller's concern
- Integration module explicitly excluded from this migration scope
