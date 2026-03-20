# Implementation Plan: state-machine-adoption

## Overview

Migrate all remaining consumers of the legacy v1 bag-of-fields state model to
read from `current`, consolidate mark-* commands into transition wrappers,
remove ghost artifact protection, and enforce NFR-1 (no inference anywhere).

**Why this order:** Model layer first (types, DTOs) because downstream consumers
depend on the field names. Then mark-* consolidation because work.py calls
mark_phase directly. Then work.py dispatch migration. Then display/validation
consumers (mechanical). Then ghost artifact removal. Then NFR-1 sweep. Then
tests and docs.

**Precondition:** `state-machine-core` must be delivered and integrated. The
engine, v1->v2 migration, CLI/API surface, and prepare/readiness adoption are
assumed present.

## Task 1: Update `TodoState` Pydantic Model

**File(s):** `teleclaude/types/todos.py`

**What:** Update the `TodoState` model (line 125) to reflect v2 schema:

- Add `current: str = ""` field — the authoritative lifecycle state
- Add `history: list[dict[str, Any]] = Field(default_factory=list)` field
- Keep `build`, `review`, `prepare_phase` fields temporarily as `str = ""`
  with deprecation comments — they are read by mark-* wrappers during
  transition and will be removed when mark-* commands are fully eliminated
- The Pydantic model validates both v1 (for raw YAML load) and v2 (for
  migrated state) shapes

**Why:** The type layer is the foundation. `api_models.py`, `roadmap.py`, and
all display code import from this model. Updating it first ensures downstream
changes have correct types to reference.

**Verification:** Existing tests that construct `TodoState` objects pass.
Builder adds a test confirming `TodoState` accepts v2 shape with `current`
and `history` fields.

---

## Task 2: Consolidate mark-* Functions into Transition Wrappers

**File(s):** `teleclaude/core/next_machine/state_io.py`

**What:** Transform `mark_phase()` (line 253), `mark_prepare_phase()` (line 321),
`mark_finalize_ready()` (line 360), and `_mark_finalize_handed_off()` (line 411)
into transition wrappers:

Each function:
1. Reads current state via `read_phase_state()` (auto-migrated to v2)
2. Instantiates the appropriate `StateMachine` (prepare or work lifecycle)
3. Fires the corresponding transition via `StateMachine.fire()`
4. Writes the result via `write_transition_state()` (from `state-machine-core`)
5. Returns the updated state

Specific mappings:
- `mark_phase(slug, "build", "started")` -> fires `start_build` transition
- `mark_phase(slug, "build", "complete")` -> fires `complete_build` transition
- `mark_phase(slug, "review", "pending")` -> fires `start_review` transition
- `mark_phase(slug, "review", "approved")` -> fires `approve_review` transition
- `mark_phase(slug, "review", "changes_requested")` -> fires `request_changes`
- `mark_prepare_phase(slug, "prepared")` -> fires `mark_prepared` transition
- `mark_finalize_ready()` -> fires `finalize_ready` transition
- `_mark_finalize_handed_off()` -> fires `finalize_handoff` transition

The review-round management, finding ID extraction, and grounding stamp logic
currently inline in these functions becomes transition actions (callables
attached to the corresponding `TransitionDefinition`).

`mark_prepare_verdict()` (line 294) and `mark_prepare_artifact()` are
orthogonal — they update nested review/artifact sub-dicts, not lifecycle
state. They remain as-is.

**Why:** FR-2 of this todo requires mark-* to route through the engine. The
existing direct field writes are the exact pattern the state machine replaces.
By making them transition wrappers, all state mutations go through the same
guarded, idempotent path.

**Verification:** Existing mark-* tests pass with updated assertions (v2
output shape instead of v1 fields). Builder adds characterization tests for
the transition wrappers if existing coverage is insufficient.

---

## Task 3: Update Work Machine Dispatch

**File(s):** `teleclaude/core/next_machine/work.py`

**What:** Update the work machine's state consumers:

- `_check_prep_complete()` (line 386): replace `state.get("prepare_phase")`
  with `state.get("current")`. Check `current == "prepared"` instead of
  `prepare_phase_val != PreparePhase.PREPARED.value`.
- Lines 514-517 (`_DispatchState` construction): replace
  `state.get(PhaseName.BUILD.value)` with status derived from `current`.
  Map `current` to build/review status equivalents.
- Line 522: replace `mark_phase(cwd, slug, BUILD, COMPLETE)` with
  `StateMachine.fire(snapshot, "complete_build", ...)` + `write_transition_state()`
- Line 558: replace `mark_phase(cwd, slug, REVIEW, PENDING)` similarly
- Line 773: replace `mark_phase(cwd, slug, BUILD, STARTED)` similarly
- Line 841: `_mark_finalize_handed_off()` is now a transition wrapper (Task 2),
  so the call remains but routes through the engine

**Why:** FR-1 of this todo requires work.py to read from `current` and fire
transitions. The direct `mark_phase` calls are the remaining v1 field-write
pattern in the work dispatch path.

**Verification:** Existing work machine tests pass with v2 state format.
Builder adds focused tests for the transition-based dispatch paths if
coverage gaps exist.

---

## Task 4: Update Display and Validation Consumers

**File(s):**
- `teleclaude/core/roadmap.py` (lines 102-103, 112, 153-164)
- `teleclaude/api_models.py` (lines 213-214, 222, 243-253)
- `teleclaude/resource_validation/__init__.py` (lines 594-600)
- `teleclaude/cli/tui/widgets/todo_row.py` (lines 223, 281, 296, 307)

**What:** Mechanical consumer migration — each reads `current` instead of
legacy field combinations:

- `roadmap.py` `_read_todo_metadata()`: replace `state.get("build")` and
  `state.get("review")` with mapping from `state.get("current")`. Update
  `_derive_phase_status()` (line 153) to derive from `current` value.
- `api_models.py`: replace `build_status`/`review_status` DTO fields with
  `current_state: str | None` and `lifecycle_phase: str | None`. Update
  `TodoDTO.from_core()` mapping.
- `resource_validation`: replace `state.build == "pending"` check with
  `current`-based readiness check.
- `todo_row.py`: update display logic to render from `current` instead of
  `build_status`/`review_status`. The TUI widget operates on in-memory
  `TodoItem` objects, so changes cascade from the DTO update.

**Why:** These are read-only consumers — they don't mutate state, they just
display it. The changes are mechanical field renames with minor mapping logic
in `_derive_phase_status`.

**Verification:** TUI reload after changes (`kill -USR2` to running TUI).
Existing tests that assert on DTO fields updated to v2 shape.

---

## Task 5: Update Guidance Strings

**File(s):** `teleclaude/core/next_machine/output_formatting.py`

**What:** Replace hardcoded `telec todo mark-phase` guidance strings with
`telec todo state` equivalents:

- Search for all `mark-phase` string references (lines 52-53, 80, 113, 123,
  144, 160, 170, 175, 186, 196)
- Replace `telec todo mark-phase {slug} --phase build --status complete` with
  `telec todo state {slug} complete_build`
- Replace `telec todo mark-phase {slug} --phase review --status approved` with
  `telec todo state {slug} approve_review`
- Similar for all other mark-phase guidance strings
- Update `mark-finalize-ready` references similarly

**Why:** Agent artifacts and CLI help text must reference the new command
surface (DoD Section 6). Agents reading stale guidance will attempt mark-*
commands instead of the transition-based equivalents.

**Verification:** Grep confirms no remaining `mark-phase` guidance strings
in output_formatting.py.

---

## Task 6: Remove Ghost Artifact Protection

**File(s):** `teleclaude/core/next_machine/prepare_events.py`

**What:** Remove the `_is_artifact_produced()` function (line 57) and its
callers (lines 95-96, 111-112, 123-124):

- The function checks `state["artifacts"][key]["produced_at"]` as a proxy for
  whether the artifact exists in a "produced" lifecycle state
- With v2, lifecycle phase is authoritative via `current` — checking artifact
  metadata as state proxy is the ghost protection pattern the parent todo
  eliminates
- Replace the `_is_artifact_produced` checks with `current`-based state
  comparisons where they guard routing decisions

**Why:** Ghost artifact protection exists because files on disk couldn't be
trusted as state. With `current` as the authoritative value, the state machine
knows what phase it's in without inspecting artifact metadata.

**Verification:** Prepare machine routing tests pass without ghost protection
fallbacks. Builder adds tests confirming routing works from `current` alone.

---

## Task 7: NFR-1 Enforcement Sweep

**File(s):** All Python source files

**What:** Codebase-wide verification that no remaining code path infers
lifecycle state from:
- `prepare_phase`, `build`, `review` as state authority
- Artifact existence (`produced_at`, file digest)
- Field combinations
- `_derive_prepare_phase` calls from runtime paths

Actions:
- Grep for remaining `state.get("prepare_phase")`, `state.get("build")`,
  `state.get("review")` outside of migration code and test characterization
- Grep for `_derive_prepare_phase` calls outside test files
- Grep for `_is_artifact_produced` calls
- Delete `_derive_prepare_phase` from runtime imports (keep in test imports
  for characterization)
- Document any remaining references with justification if they serve a
  non-inference purpose (e.g., migration mapper)

**Why:** NFR-1 requires no inference anywhere. This sweep is the enforcement
pass that confirms the migration is complete.

**Verification:** Grep sweep results show zero remaining inference-based state
access outside migration code and characterization tests.

---

## Task 8: Update Tests

**File(s):**
- `tests/unit/core/next_machine/test_state_io.py`
- `tests/unit/core/next_machine/test_work.py` (if exists)
- `tests/unit/core/next_machine/test_prepare_events.py`
- Other test files constructing v1 state dicts

**What:**
- Tests that mock or construct `mark_phase` return values must return v2 format
- Tests for work.py dispatch must use v2 state format
- Tests for `_is_artifact_produced` become characterization tests for the
  removed function, or are deleted if the function is removed
- Tests asserting on `state["build"]`/`state["review"]` updated to
  `state["current"]`
- New tests for transition wrappers (Task 2) if existing coverage is insufficient

**Why:** Consumer migration changes the contract. Tests must match the new
contract to avoid false failures.

**Verification:** Full test suite passes: `make test` with no failures.

---

## Task 9: Agent Artifact and Help Text Updates

**File(s):**
- Agent skills/commands referencing mark-* commands
- CLI help text in tool command docstrings

**What:**
- Search agent artifacts for `mark-phase`, `mark-ready`, `mark-finalize-ready`
  references
- Update to reference `telec todo state <slug> <transition>` equivalents
- Update CLI help text docstrings in tool commands to reference the new surface
- The mark-* CLI commands remain as backward-compatible wrappers but their
  help text notes they are deprecated in favor of `telec todo state`

**Why:** DoD Section 6 requires CLI help text and agent artifacts to reflect
current behavior. Agent prompts that reference removed commands cause runtime
failures.

**Verification:** Grep confirms no stale mark-* references in agent artifacts
or help text outside of deprecation notices.

---

## Risks

- **Transition wrapper fidelity:** The mark-* functions contain inline logic
  (review round management, finding ID extraction, grounding stamps). Moving
  this logic into transition actions must preserve exact behavior. Mitigation:
  existing tests characterize the current behavior — they must pass after
  conversion.
- **DTO field rename cascade:** Renaming `build_status`/`review_status` to
  `current_state` in DTOs may break web frontend or adapter code that reads
  these fields. Mitigation: search for field name references in web/ and
  adapter/ directories before renaming.
- **Work.py concurrent state:** Multiple agents may read/write work state
  concurrently. The transition engine's idempotent semantics handle re-fires,
  but concurrent reads of partially-written state remain a risk. Mitigation:
  the existing single-flight guard in work.py already prevents concurrent
  execution per slug.
