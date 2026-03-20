# Requirements: state-machine-versioning

## Goal

Replace the bag-of-fields `state.yaml` with a versioned state machine where the current state is a single authoritative value, transitions are atomic and guarded, and history enables rewind. Eliminate all inference-based state derivation, field-by-field patching, and ghost artifact protection hacks.

## Scope

### In scope

- State machine core: states, transitions, guards, and action handling defined in code
- Versioned transition history with rewind capability
- New `telec todo state` CLI command surface
- Schema versioning with v1 -> v2 migration
- Replacement of the existing prepare-phase inference helper with authoritative state
- Replacement of mark-* field-patch commands with transition-based operations
- Elimination of ghost artifact protection (`produced_at` existence checks as state proxy)
- Elimination of digest-based staleness loops as state inference mechanism
- Prepare state machine (Phase A) migration to the new model
- Work state machine (Phase B) migration to the new model
- Integration state machine (Phase C) migration to the new model

### Out of scope

- `roadmap.yaml` structure changes: roadmap is item metadata, not lifecycle state [inferred]
- DOR scoring algorithm changes: DOR assessment is a gate check, not a state transition [inferred]
- Creative lifecycle state machines: separate domain with its own state model [inferred]
- Changes to the artifact file format (`.md` files themselves) [inferred]

## Functional Requirements

### FR-1: Authoritative State Value

The state machine must maintain a single `current` field that is the sole source of truth for lifecycle phase. No code path may infer the current state from artifact existence, file digests, or field combinations.

**Success criteria:**

- The existing prepare-phase derivation helper and equivalent inference logic are removed
- Every state query resolves from the `current` field, never from file system inspection
- Attempting to read state always returns a concrete state value, never a derived one

### FR-2: Atomic Guarded Transitions

State changes happen through named transitions with precondition guards. A transition either succeeds atomically (state + history updated together) or fails with a clear rejection message.

**Success criteria:**

- Each transition declares its source state(s) and target state
- Guards validate preconditions before the transition fires
- If the guard fails, the state is unchanged and the caller receives a diagnostic explaining why
- No partial state updates are possible (no field-by-field patching)

### FR-3: Idempotent Transition Semantics

Transitions follow the idempotency rules described in the input:

- Already past the target state -> no-op (success, no state change)
- At the required source state -> fires the transition
- Not yet at the required source state -> rejects with diagnostic ("current state is X, transition Y requires state Z")

**Success criteria:**

- Firing a transition when already past it does not error or re-execute actions
- The idempotency check is part of the transition engine, not per-transition custom logic

### FR-4: Versioned Transition History

Every transition appends an entry to a history log within the state blob. History entries capture the transition metadata needed for audit and rewind.

**Success criteria:**

- History entries include: source state, target state, timestamp, actor identity (session ID), and transition-specific metadata (for example verdict value or digest) [inferred]
- History is append-only during normal operation
- History survives serialization round-trips (YAML read/write)

### FR-5: Rewind Capability

The state machine supports reverting to the previous state by popping the most recent history entry.

**Success criteria:**

- `telec todo state <slug> --rewind` restores the previous state from history
- Rewind on an empty history (initial state) is rejected with a clear message
- Rewind updates the `current` field atomically with the history pop

### FR-6: Steps as Functions

Transition behavior is defined in code, not in external YAML/JSON step configuration. The step definition remains a code-level callable rather than a data-driven lookup.

**Success criteria:**

- Core transition definitions are represented as code-defined callables rather than configuration lookups
- The transition engine executes transitions through one consistent callable contract
- Adding a new transition does not require adding new external transition configuration

### FR-7: CLI Command Surface

A new `telec todo state` command provides state inspection and transition firing.

**Success criteria:**

- `telec todo state <slug>` displays current state, history summary, and valid transitions from current state
- `telec todo state <slug> <transition>` fires a named transition (idempotent per FR-3)
- `telec todo state <slug> --rewind` pops to the previous state (per FR-5)
- Command output exposes the current state and valid transitions explicitly enough for both human and agent consumers

### FR-8: Schema Versioning and Migration

The new state blob carries a `schema_version` field. A migration path from the current v1 bag-of-fields format to the new v2 state machine format exists.

**Success criteria:**

- Existing `state.yaml` files (`schema_version: 1`) are migrated to v2 on first read
- Migration maps the current bag-of-fields into the closest equivalent v2 state based on field values [inferred: the mapping must handle the combinations currently used by prepare/work lifecycle state]
- The migration is idempotent: reading an already-migrated v2 file does not re-migrate
- The migration helper is reusable for future v2 -> v3 transitions

### FR-9: Mark-Command Consolidation

The existing `mark-ready`, `mark-phase`, `mark-finalize-ready`, and `mark-prepare-phase` commands are replaced by transition-based equivalents. The `telec todo state <slug> <transition>` surface subsumes their functionality.

**Success criteria:**

- Each mark-* operation maps to one or more named transitions
- The old mark-* CLI commands are removed or become thin wrappers that fire the corresponding transition [inferred: thin wrappers may be needed for backward compatibility during rollout, but the goal is elimination]
- Agent artifacts, procedures, and CLI help text that reference mark-* commands are updated

### FR-10: Prepare, Work, and Integration Machine Coverage

The prepare lifecycle (Phase A), work lifecycle (Phase B), and integration lifecycle (Phase C) are all expressed through the new state model rather than through field inference or checkpoint-specific ad hoc sequencing.

**Success criteria:**

- All current prepare lifecycle states map to states in the v2 model
- All current work lifecycle transitions map to states or transitions in the v2 model
- All current integration lifecycle phases map to states or transitions in the new model [inferred]
- The prepare/work/integration orchestrator flows drive lifecycle advancement through the transition engine rather than through direct field writes or phase re-derivation

## Non-Functional Requirements

### NFR-1: No State Inference Anywhere

After migration, no code path in the codebase may infer lifecycle state from artifact existence, file digests, field combinations, or checkpoint-specific state reconstruction. The authoritative current state value is the sole lifecycle authority.

### NFR-2: Backward-Compatible Persistence

Lifecycle persistence remains in the existing file-backed formats used by each machine, and external consumers must continue to find the information they need either in the new structure or through a compatibility accessor. [inferred]

### NFR-3: Atomic Writes

Lifecycle state writes remain atomic (write-then-rename or equivalent) to prevent corruption from concurrent access or crashes mid-write. [inferred]

## Acceptance Criteria

- [ ] The existing prepare-phase derivation helper is deleted and no equivalent inference exists
- [ ] Ghost artifact protection (`produced_at` existence checks) is removed as a state proxy
- [ ] All mark-* commands route through the transition engine
- [ ] `telec todo state <slug>` shows current state and valid transitions
- [ ] Existing v1 lifecycle state files migrate cleanly to the new model
- [ ] Rewind restores the previous state from history
- [ ] Prepare, work, and integration lifecycle routing all use the new state model
- [ ] Pre-commit hooks pass (lint, typecheck, tests) [inferred]
- [ ] All existing tests updated or replaced to match the new model [inferred]

## Dependency / Prerequisites

- No blocking dependencies in `roadmap.yaml` [inferred]
- The iceboxed `workflow-engine-refactor` todo is architecturally superseded by this work because it builds on the broken state model rather than replacing it [inferred]

## Constraints

- Must not break running orchestrator sessions during migration: legacy state encountered at runtime is migrated on read [inferred]
- Must preserve the audit trail information currently stored in lifecycle state [inferred: existing review metadata and timestamps remain recoverable from transition history]
- Phase C is not exempt from the new model even if it continues to use its existing checkpoint location or file format [inferred]

## Risks

- **Scope size:** This change touches a broad lifecycle state surface across prepare, work, and integration code paths [inferred]. The draft phase should assess whether splitting into foundation and adoption work is warranted.
- **Agent artifact drift:** Procedures, command artifacts, and CLI help text reference current mark-* commands and state field names. These must be updated atomically with the code changes to prevent agent confusion.
- **Concurrent state access:** Multiple agent sessions may read or write lifecycle state concurrently. The transition engine must handle this safely [inferred: current atomic-write guarantees need to be preserved].
