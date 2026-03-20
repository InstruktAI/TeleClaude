# Requirements: state-machine-adoption

## Goal

Complete the v1-to-v2 state model migration across all remaining consumers.
After `state-machine-core` delivers the engine, migration, CLI surface, and
initial prepare/readiness adoption, this todo migrates every other consumer of
the legacy bag-of-fields model to read from `current`, consolidates mark-*
commands into transition wrappers, removes ghost artifact protection, and
enforces NFR-1 (no inference anywhere).

## Scope

### In scope

- Consumer migration: all code paths that read `prepare_phase`, `build`, or
  `review` as top-level state fields switch to reading `current`
- Mark-* command consolidation: `mark-phase`, `mark-ready`,
  `mark-finalize-ready`, and `mark-prepare-phase` become thin wrappers that
  fire corresponding transitions through the `StateMachine` engine
- Ghost artifact protection removal: `produced_at` existence checks used as
  state proxy are eliminated (state is authoritative via `current`)
- Work machine (Phase B) adoption: `work.py` dispatch reads `current` and
  fires transitions instead of calling `mark_phase` directly
- NFR-1 enforcement: codebase-wide verification that no code path infers
  lifecycle state from artifact existence, file digests, or field combinations
- Pydantic model updates: `TodoState` in `types/todos.py` reflects v2 schema
- DTO/API model updates: `api_models.py` maps from v2 state fields
- Display layer updates: `roadmap.py`, `todo_row.py`, `output_formatting.py`
  read `current` instead of legacy fields
- Resource validation updates: `resource_validation/__init__.py` uses `current`
- Agent artifact/procedure/CLI help text migration from mark-* to
  `telec todo state`

### Out of scope

- Integration machine (Phase C) refactor: the integration module
  (`teleclaude/core/integration/`) already has its own working state machine
  (`IntegrationCheckpoint` + `IntegrationPhase` + step functions). It does NOT
  use the bag-of-fields model and does NOT suffer from the inference, ghost
  artifact, or field-patching problems this work addresses. Refactoring it to
  use the generic `StateMachine` engine is a consistency improvement, not a
  correctness fix, and is architecturally separate from the v1->v2 consumer
  migration. [inferred: recommend a dedicated follow-up todo if unification is desired]

## Functional Requirements

### FR-1: Work Machine Transition Adoption

The work machine dispatch in `work.py` reads `current` for phase checks and
fires transitions through the `StateMachine` engine instead of calling
`mark_phase()` directly.

**Success criteria:**

- `next_work()` precondition checks read `state["current"]` instead of
  `state.get("prepare_phase")`
- Build/review status advancement uses `StateMachine.fire()` instead of direct
  `mark_phase()` calls
- The `_mark_finalize_handed_off()` call routes through the transition engine
- No direct field writes for lifecycle state remain in `work.py`

### FR-2: Mark-* Command Consolidation

The existing `mark_phase`, `mark_prepare_phase`, `mark_ready`, and
`mark_finalize_ready` functions become thin wrappers that fire the
corresponding transition through the `StateMachine` engine.

**Success criteria:**

- Each mark-* function reads the current v2 state, fires the appropriate
  transition via `StateMachine.fire()`, and writes the result
- The CLI surface and API routes for mark-* commands continue to work
  (backward compatibility for in-flight agent sessions)
- The wrappers produce the same observable state changes as the current
  direct-write implementations

### FR-3: Ghost Artifact Protection Removal

The `produced_at` existence checks in `prepare_events.py` that serve as
state proxy are removed. State authority comes from `current`, not from
whether an artifact has a `produced_at` timestamp.

**Success criteria:**

- `_is_artifact_produced()` checks in `prepare_events.py` are removed or
  replaced with `current`-based state checks
- No code path uses artifact metadata (`produced_at`, `digest`) as a proxy
  for lifecycle phase

### FR-4: Consumer Model Updates

All remaining consumers of the legacy field model switch to v2 format.

**Success criteria:**

- `TodoState` Pydantic model in `types/todos.py` replaces `build`, `review`,
  `prepare_phase` top-level fields with `current` and `history`
- `TodoDTO`/`TodoInfo` in `api_models.py` maps from v2 fields
- `roadmap.py` reads `current` instead of `build`/`review`
- `resource_validation/__init__.py` checks `current` instead of `build`
- `todo_row.py` TUI widget reads `current` for display
- `output_formatting.py` guidance strings reference `telec todo state`
  instead of `telec todo mark-phase`

### FR-5: NFR-1 Enforcement

After all consumer migrations, no code path in the codebase infers lifecycle
state from artifact existence, file digests, field combinations, or
checkpoint-specific state reconstruction (excluding the integration module
which has its own separate state system).

**Success criteria:**

- A grep/search sweep confirms no remaining references to `prepare_phase`,
  `state["build"]`, or `state["review"]` as state authority outside of
  migration code and test characterization
- The `_derive_prepare_phase` function is either deleted or marked as
  migration-only (not called from any runtime path)

## Non-Functional Requirements

### NFR-1: Backward Compatibility During Rollout

Mark-* CLI commands and API routes remain functional as thin wrappers for
the transition period. They can be deprecated in a future todo.

## Acceptance Criteria

- [ ] `work.py` dispatch reads `current` and fires transitions
- [ ] All mark-* functions route through `StateMachine.fire()`
- [ ] Ghost artifact protection (`produced_at` state proxy) removed
- [ ] `TodoState` model reflects v2 schema
- [ ] `api_models.py` maps from v2 fields
- [ ] `roadmap.py`, `todo_row.py`, `output_formatting.py` read `current`
- [ ] `resource_validation` uses `current`
- [ ] No codebase path infers state from fields/artifacts (NFR-1)
- [ ] Agent artifacts and help text reference `telec todo state`
- [ ] Pre-commit hooks pass (lint, typecheck, tests)
- [ ] All existing tests updated to v2 state format

## Dependencies

- Depends on `state-machine-core` (engine, migration, CLI/API surface)

## Constraints

- Mark-* commands remain as wrappers (not deleted) for backward compatibility
- Must not break running agent sessions during transition
- Integration module is explicitly excluded from this migration scope
