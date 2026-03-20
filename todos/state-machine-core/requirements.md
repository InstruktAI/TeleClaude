# Requirements: state-machine-core

## Goal

Deliver the state machine engine, v1-to-v2 schema migration, CLI/API inspection
surface, and initial routing adoption in the prepare machine and work-readiness
check. This is the foundation that proves the new model works before the broader
codebase adoption in the follow-up `state-machine-adoption` todo.

## Scope

### In scope

- State machine engine: states, transitions, guards, actions, idempotent semantics
- Versioned transition history with rewind capability
- New `telec todo state` CLI command surface
- Schema versioning with v1 -> v2 on-read migration
- Prepare router reads `current` instead of inferring from `prepare_phase` + `_derive_prepare_phase`
- `is_ready_for_work` reads `current` instead of multi-field inference
- Write path for v2 snapshots (atomic, no legacy field injection)
- API route for `POST /todos/state` with inspection, transition firing, and rewind

### Out of scope (deferred to state-machine-adoption)

- Mark-command consolidation (FR-9 of parent): mark-* commands remain functional
  during the transition period — they write legacy fields that get re-migrated on
  next read
- Full consumer migration: work.py dispatch, roadmap.py, api_models.py,
  types/todos.py, resource_validation, TUI widgets, output_formatting
- Ghost artifact protection removal
- Integration machine (Phase C) adoption
- NFR-1 codebase-wide enforcement (no inference anywhere)
- Agent artifact/procedure/help text migration from mark-* to `telec todo state`

## Functional Requirements

### FR-1: Authoritative State Value

The state machine maintains a single `current` field as the sole source of truth
for lifecycle phase. The prepare router and `is_ready_for_work` resolve from
`current`, not from field combinations or artifact existence.

**Success criteria:**

- `next_prepare()` reads `state["current"]` and maps to `PreparePhase` directly
- The `_derive_prepare_phase` fallback path is removed from `next_prepare()`
- `is_ready_for_work()` checks `state["current"]` instead of multi-field inference
- Both the `_apply_stale_artifact_reroute` function and the prepare routing block
  write/read `current` instead of `prepare_phase`

### FR-2: Atomic Guarded Transitions

State changes happen through named transitions with precondition guards. A
transition either succeeds atomically (state + history updated together) or
fails with a typed rejection.

**Success criteria:**

- Each transition declares source state(s) and target state
- Guards validate preconditions before the transition fires
- If the guard fails, the state is unchanged and the caller receives a
  `TransitionRejected` exception with diagnostic attributes
- No partial state updates are possible through the engine

### FR-3: Idempotent Transition Semantics

Transitions follow idempotency rules:

- Already past the target state -> no-op (success, no state change, action not called)
- At the required source state -> fires the transition
- Not yet at the required source state -> rejects with diagnostic

**Success criteria:**

- Idempotency is built into the engine, not per-transition custom logic
- The "past" check uses the ordered states list for index comparison

### FR-4: Versioned Transition History

Every transition appends a history entry capturing transition metadata.

**Success criteria:**

- History entries include: source state, target state, transition name,
  timestamp, actor identity (session ID), and transition-specific metadata
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
- Migration derives `current` from the existing field combination
  (`prepare_phase`, `build`, `review`, `finalize.status`)
- Legacy top-level fields (`prepare_phase`, `build`, `review`) are removed from
  the migrated blob
- V2 blobs skip the deep-merge with `default_state()` (they are self-contained)
- Migration is idempotent: reading a v2 file does not re-migrate
- The migration helper is reusable for future version transitions

## Non-Functional Requirements

### NFR-1: Backward-Compatible Persistence During Transition

Mark-* functions continue to work during the transition period. They read
v2-migrated state, write legacy fields, and the next read re-migrates. This
hybrid state is acceptable until `state-machine-adoption` completes.

### NFR-2: Atomic Writes

State writes remain atomic (YAML dump to file) to prevent corruption. The new
`write_transition` helper writes v2 snapshots without injecting legacy fields.

## Acceptance Criteria

- [ ] `StateMachine` engine passes all 5 engine spec tests
- [ ] `read_phase_state()` migrates v1 state to v2 on read
- [ ] `read_phase_state()` returns v2 blobs without legacy field reintroduction
- [ ] `next_prepare()` routes from `current`, not `prepare_phase` + inference
- [ ] `is_ready_for_work()` uses `current` instead of multi-field checks
- [ ] `telec todo state <slug>` shows current state and valid transitions
- [ ] `telec todo state <slug> <transition>` fires a transition
- [ ] `telec todo state <slug> --rewind` restores previous state
- [ ] API route `POST /todos/state` handles inspection, transition, and rewind
- [ ] Existing mark-* commands continue to work (hybrid re-migration)
- [ ] Pre-commit hooks pass (lint, typecheck, tests)

## Dependencies

- No blocking dependencies. Parent `state-machine-versioning` is a container.
- `state-machine-adoption` depends on this todo completing first.

## Constraints

- Must not break running orchestrator sessions: legacy state migrates on read
- Mark-* commands remain functional (they write v1 fields that re-migrate)
- The engine is pure (no I/O, no filesystem) — persistence is the caller's concern
