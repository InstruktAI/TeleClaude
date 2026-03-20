# Implementation Plan: state-machine-core

## Overview

Deliver the state machine engine, v1-to-v2 on-read migration, CLI/API surface,
and prepare/work-readiness adoption. The engine is a pure stateless transformer —
no I/O, no YAML, no filesystem. It receives a snapshot dict and returns a new
snapshot dict. Persistence is the caller's responsibility.

**Why this approach:** The engine must be built first because every other component
depends on it. The v1->v2 migration comes next because it makes existing state
files usable by the engine. CLI/API follows because it exposes the engine for
inspection. Prepare router and `is_ready_for_work` adoption are included because
they're the two highest-value consumers — they replace `_derive_prepare_phase`
inference and multi-field readiness checks, proving the model works in production.

**Task order:** Engine -> migration -> write path -> prepare adoption ->
readiness adoption -> CLI surface -> CLI handler -> API route -> test updates.

## Task 1: Create the State Machine Engine

**File(s):** `teleclaude/core/next_machine/state_machine.py` (new)

**What:** A generic `StateMachine` class that manages state snapshots through
named transitions with guards, actions, idempotent semantics, and rewind.

- `TransitionDefinition` — frozen dataclass with fields:
  `name: str`, `sources: frozenset[str]`, `target: str`,
  `action: Callable[[dict, dict], dict] | None`,
  `guard: Callable[[dict, dict], bool] | None`
- `StateMachine` — constructor takes:
  `states: list[str]` (ordered for "past" comparison via index),
  `transitions: list[TransitionDefinition]`
- `fire(snapshot, transition, actor_id, at, metadata)` — idempotent:
  - Current in sources -> run guard (if present, raise `TransitionRejected` on
    failure) -> run action (if present) -> set `current` to target -> append
    history entry -> return updated snapshot
  - Current past target (higher state index) -> no-op, return snapshot unchanged
  - Current before sources -> raise `TransitionRejected(current, transition, required_sources)`
- `rewind(snapshot)` — pop last history entry, set `current` to popped entry's
  `source`. Empty history -> raise `RewindRejected(current)`
- `TransitionRejected` and `RewindRejected` — exception classes with typed
  attributes for diagnostic reporting
- History entry format: `{"source", "target", "transition", "at", "by", "metadata"}`
- The engine is pure — no I/O. It transforms snapshot dicts.

**Why:** FR-2 (atomic guarded transitions) and FR-6 (steps as functions) require
a reusable engine. Keeping it pure means prepare, work, and integration machines
all use the same engine without coupling to persistence. The `states` list
ordering is the mechanism for FR-3 (idempotent "already past" check).

**Verification:** Makes GREEN:
- `test_fire_advances_current_records_history_and_runs_callable_action`
- `test_fire_is_a_noop_when_current_state_is_already_past_the_target`
- `test_fire_rejects_when_transition_source_state_has_not_been_reached`
- `test_rewind_restores_previous_current_value_and_pops_last_history_entry`
- `test_rewind_rejects_when_the_machine_has_no_history`

---

## Task 2: Add v1 -> v2 Migration in `read_phase_state`

**File(s):** `teleclaude/core/next_machine/state_io.py`

**What:** After YAML load and before return in `read_phase_state()` (line 201),
add a migration branch when `schema_version` is 1 or absent:

- Derive `current` from existing field combination:
  - If `prepare_phase` is set and not `"prepared"` -> `current = prepare_phase`
  - If `prepare_phase == "prepared"` and `build == "pending"` -> `current = "build_pending"`
  - If `build == "started"` -> `current = "build_started"`
  - If `build == "complete"` and `review == "pending"` -> `current = "review_pending"`
  - If `review` in `("approved", "changes_requested")` -> `current = "review_{status}"`
  - If `finalize.status == "ready"` -> `current = "finalize_ready"`
  - If `finalize.status == "handed_off"` -> `current = "finalize_handed_off"`
  - Fallback -> `current = prepare_phase or "input_assessment"`
- Set `schema_version = 2`, `history = []`
- Remove legacy top-level fields: `prepare_phase`, `build`, `review`

When `schema_version` is already 2:
- Return the blob as-is, skipping the `_deep_merge_state(default_state(), ...)`
  call. V2 blobs are self-contained — deep-merging would reintroduce legacy
  fields from `default_state()`.

The existing `default_state()` function in `_types.py` still returns v1 shape
for new state creation. The migration path is read-only — it promotes what's
on disk without changing what `default_state()` produces. This keeps mark-*
commands working (they call `default_state()` then patch fields).

**Why:** FR-8 requires on-read migration so existing v1 files work seamlessly.
Removing legacy fields from the migrated blob forces early consumers (prepare
router, `is_ready_for_work`) to use `current` (FR-1). The deep-merge skip for
v2 prevents `default_state()` defaults from bleeding back into migrated state.

**Verification:** Makes GREEN:
- `test_read_phase_state_migrates_legacy_prepare_state_into_v2_current`
- `test_read_phase_state_keeps_existing_v2_blob_without_reintroducing_legacy_fields`

---

## Task 3: Add v2 Write Path

**File(s):** `teleclaude/core/next_machine/state_io.py`

**What:** Add a `write_transition_state(cwd, slug, snapshot)` function near
`write_phase_state()` (line 240):

- Accepts a v2 snapshot dict from `StateMachine.fire()` or `rewind()`
- Writes the snapshot as YAML using the existing `write_text_sync` and
  `yaml.dump` pattern (atomic write-to-file)
- Does NOT inject legacy fields — the v2 snapshot is written as-is
- The existing `write_phase_state()` remains unchanged for mark-* compatibility

**Why:** NFR-2 requires atomic writes. The existing `write_phase_state` writes
atomically but doesn't distinguish v1 from v2. The new function makes the v2
write path explicit and ensures no legacy field contamination. Mark-* functions
continue using `write_phase_state` — the hybrid re-migrates on next read.

**Verification:** Verified transitively through Task 8 (API route) integration.
Builder should add a unit test if the write path has non-trivial logic beyond
YAML dump.

---

## Task 4: Update Prepare Machine Routing

**File(s):** `teleclaude/core/next_machine/prepare.py`

**What:** In `next_prepare()`, replace the phase-resolution block (lines 110-115):

Current code reads `state.get("prepare_phase")` and falls back to
`_derive_prepare_phase()`. Replace with:

```python
raw_phase = str(state.get("current", "")).strip()
try:
    phase = PreparePhase(raw_phase)
except ValueError:
    phase = PreparePhase.INPUT_ASSESSMENT
```

- Read `state["current"]` (guaranteed present after v2 migration in Task 2)
- Map to `PreparePhase` enum directly
- Remove the `_derive_prepare_phase` import and fallback path
- Update `_apply_stale_artifact_reroute` (line 44) to write `state["current"]`
  instead of `state["prepare_phase"]`

The `_derive_prepare_phase` function in `prepare_events.py` is NOT deleted — it
remains available for the migration mapper (Task 2 may reuse its logic) and for
characterization tests. It is simply no longer called from `next_prepare()`.

**Why:** FR-1 requires the authoritative `current` value as the sole routing
source. The `_derive_prepare_phase` fallback is the exact inference logic this
todo eliminates from the runtime path.

**Verification:** Makes GREEN:
- `test_next_prepare_routes_from_current_without_phase_derivation`

---

## Task 5: Update `is_ready_for_work`

**File(s):** `teleclaude/core/next_machine/slug_resolution.py`

**What:** Replace the multi-field check in `is_ready_for_work()` (lines 235-251):

Current code checks `phase`, `build`, `review`, and `dor.score`. Replace with:

```python
state = read_phase_state(cwd, slug)
phase = state.get("phase")
if phase != ItemPhase.PENDING.value:
    return False
current = state.get("current", "")
return current == "prepared"
```

- The `phase == PENDING` precondition remains — items not yet started should
  still be in pending item phase (this is `phase`, not `current`)
- The `build`, `dor.score`, and `PhaseStatus` checks are removed — v2 encodes
  readiness in the `current` value itself: "prepared" means all gates passed

**Why:** FR-1 requires all state queries to resolve from `current`. The existing
multi-field inference (`build == pending AND dor.score >= 8 OR build == complete`)
is replaced by a single value check.

**Verification:** Makes GREEN:
- `test_is_ready_for_work_uses_current_authoritative_state_value`

---

## Task 6: Add CLI Surface Definition

**File(s):** `teleclaude/cli/telec/surface.py`

**What:** Add a `state` subcommand to the `todo` command's `subcommands` dict,
after `mark-finalize-ready` (line 501):

```python
"state": CommandDef(
    desc="Inspect or advance lifecycle state",
    args="<slug> [<transition>]",
    flags=[
        _H,
        Flag("--rewind", desc="Revert to the previous state from history"),
    ],
    auth=CommandAuth(system=_SYS_ALL, human=_HR_MEMBER_CONTRIB),
),
```

Auth rationale: `_SYS_ALL` allows all system roles (orchestrator, worker,
integrator) to inspect and fire transitions. `_HR_MEMBER_CONTRIB` matches
mark-phase's human access level.

**Why:** FR-7 defines the CLI surface. The surface definition feeds agent system
prompts (CLI help text is DoD Section 6). Auth must be broad because state
inspection is needed by all roles.

**Verification:** Makes GREEN:
- `test_todo_surface_exposes_state_subcommand_with_rewind_flag`

---

## Task 7: Add CLI Handler Routing

**File(s):** `teleclaude/cli/telec/handlers/todo.py`

**What:** In `_handle_todo()` (line 59), add routing for the `state` subcommand:

- The handler already uses a `subcommand` variable from `args[0]`
- Add `elif subcommand == "state": handle_todo_state(args[1:])` before the
  unknown-subcommand branch
- Import `handle_todo_state` from `teleclaude.cli.tool_commands` alongside
  the existing `handle_todo_mark_phase` import

**Why:** Connects the surface definition (Task 6) to the tool command handler
(Task 8). Follows the existing pattern for mark-phase routing.

**Verification:** Makes GREEN:
- `test_handle_todo_routes_state_subcommand_to_tool_command_handler`

---

## Task 8: Add Tool Command Handler

**File(s):** `teleclaude/cli/tool_commands/todo.py`

**What:** Add `handle_todo_state(args: list[str])` function following the
`handle_todo_mark_phase` pattern (line 330):

- Parse args: first positional is `slug`, optional second is `transition`,
  `--rewind` flag triggers rewind mode
- Build JSON body: always include `slug` and `cwd` (`os.getcwd()`)
- If transition provided: add `transition: <name>`
- If `--rewind` flag: add `rewind: True`
- Call `tool_api_call("POST", "/todos/state", json_body=body)`
- Print response via `print_json`
- Add `handle_todo_state` to the module's `__all__` list (line 24)

**Why:** The tool command handler bridges CLI to API. Following the existing
`handle_todo_mark_phase` pattern ensures consistency and reviewer familiarity.

**Verification:** Makes GREEN:
- `test_handle_todo_state_reads_current_snapshot_when_only_slug_is_provided`
- `test_handle_todo_state_fires_a_named_transition`
- `test_handle_todo_state_requests_rewind`

---

## Task 9: Add API Route

**File(s):** `teleclaude/api/todo_routes.py`

**What:** Add `POST /todos/state` route handler following the `/todos/mark-phase`
pattern (line 141):

- Read request body: `slug`, `cwd`, optional `transition`, optional `rewind`
- Apply `clearance_todos_mark_phase` dependency (or define a new clearance
  function with the same access level as the surface auth)
- Read state via `read_phase_state(cwd, slug)` — auto-migrated to v2 by Task 2
- **Inspection mode** (no transition, no rewind): return JSON with `current`,
  `history`, and `valid_transitions` (transition names whose sources include
  `current`)
- **Transition mode**: instantiate the appropriate `StateMachine` for the slug's
  lifecycle, call `fire()`, write state back via `write_transition_state()`,
  return updated snapshot
- **Rewind mode**: instantiate machine, call `rewind()`, write back, return
  updated snapshot
- Error handling: catch `TransitionRejected`/`RewindRejected` and return 409
  with diagnostic JSON

For the initial delivery, the "appropriate StateMachine" instantiation uses a
factory function that returns a `StateMachine` with prepare-lifecycle states and
transitions. Work-lifecycle and integration-lifecycle machines are added in
`state-machine-adoption`.

**Why:** FR-7 requires `telec todo state <slug>` to work end-to-end. The CLI
routes through the API. The route must validate auth, handle all three modes,
and return structured responses. Using 409 for transition rejections follows
HTTP semantics (conflict with current state).

**Verification:** The builder must add a route-level test that exercises
the API handler directly (not just the tool command mock). This addresses
review finding I2 from the parent plan review — transitive coverage through
mocked `tool_api_call` does not prove route validation, auth hookup, or
response contract.

---

## Task 10: Update Existing Tests

**File(s):**
- `tests/unit/core/next_machine/test_state_io.py`
- `tests/unit/core/next_machine/test_prepare_events.py`
- Other test files that construct v1 state dicts and assert on legacy fields

**What:** Tests that construct state dicts with `prepare_phase`, `build`, `review`
as top-level fields need updating to account for auto-migration:

- Tests calling `read_phase_state()` on v1 input should expect v2 output (with
  `current` and without legacy fields)
- Tests that mock `read_phase_state` return values should return v2 format
- Tests for `_derive_prepare_phase` remain valid as characterization tests for
  the migration mapper — they verify the field-to-state mapping logic
- Tests asserting on `state["prepare_phase"]` or `state["build"]` need updating
  to assert on `state["current"]`

**Why:** The v1->v2 migration changes `read_phase_state`'s output contract. All
consumers of the old contract must adapt. Leaving tests asserting on removed
fields causes false failures.

**Verification:** Full test suite passes: `make test` with no failures.

---

## Risks

- **Hybrid state during transition:** Mark-* functions write legacy fields into
  v2-migrated state, creating hybrids. The re-migration on next read handles
  this, but concurrent reads could see stale data. Mitigated by: single-flight
  guards already exist in work.py, and prepare.py reads state fresh each
  iteration.
- **State ordering for "past" check:** The engine determines "already past" by
  comparing state indices in the ordered states list. If the states list doesn't
  match the actual lifecycle order, idempotent no-ops could fire incorrectly.
  Mitigated by: test spec explicitly verifies this behavior.
- **Migration mapper completeness:** The v1->v2 mapper must handle all field
  combinations currently in production state.yaml files. The builder must add
  TDD tests for work-phase migration (build/review/finalize field combinations)
  beyond the prepare-phase migration covered by existing specs.
- **Route-level test gap:** Task 9 requires the builder to add a test that
  exercises the API route directly. The test spec files don't include this —
  it's builder-driven TDD based on the existing route test patterns in the
  codebase.
