# Implementation Plan: state-machine-versioning

## Overview

Replace the bag-of-fields `state.yaml` with a versioned state machine where `current`
is the sole source of truth for lifecycle phase. Nine tasks, ordered by dependency:
engine first, then migration + consumer updates as an atomic batch, then surface
additions, then verification.

The key constraint is "no hybrid intermediate state" — once `read_phase_state()` returns
v2 format (without `build`/`review`/`prepare_phase`), ALL consumers must handle v2.
Tasks 3–7 must be implemented in close succession.

---

## Task 1: Create the StateMachine engine module

**What:** New file `teleclaude/core/next_machine/state_machine.py` containing:

- `TransitionDefinition` dataclass: `name`, `sources` (set of state names), `target`,
  optional `guard` and `action` callables
- `StateMachine` dataclass: `states` (ordered list), `transitions` list
  - `fire(snapshot, transition, actor_id, at, metadata=None) -> dict`:
    1. Look up transition by name
    2. If `snapshot["current"]` is in `sources` → execute guard (if any), execute
       action (if any), set `current` to `target`, append history entry
    3. If `states.index(current) > states.index(target)` → no-op (return snapshot
       unchanged, action NOT re-executed)
    4. Otherwise → raise `TransitionRejected`
  - `rewind(snapshot) -> dict`: pop last history entry, set `current` to popped
    entry's `source`. Empty history → raise `RewindRejected`
- `TransitionRejected` exception with `current`, `transition`, `required_sources` attrs
- `RewindRejected` exception with `current` attr

**Why:** The engine is the foundation for all other tasks. Keeping it pure (no I/O, no
filesystem, no imports from state_io) means it's independently testable and composable.
The fire algorithm (source check → past check → reject) naturally handles both linear
progression (prepare phases) and cyclic transitions (review → build restart) because the
source-set check takes priority over the ordered-index past check.

**Verification:** Remove xfail markers and make GREEN:

- `test_fire_advances_current_records_history_and_runs_callable_action`
- `test_fire_is_a_noop_when_current_state_is_already_past_the_target`
- `test_fire_rejects_when_transition_source_state_has_not_been_reached`
- `test_rewind_restores_previous_current_value_and_pops_last_history_entry`
- `test_rewind_rejects_when_the_machine_has_no_history`

**Files:**

- New: `teleclaude/core/next_machine/state_machine.py`

---

## Task 2: Update TodoState model and default_state

**What:** Modify `TodoState` in `teleclaude/types/todos.py`:

- Change `schema_version` default from `1` to `2`
- Add `current: str = "input_assessment"`
- Add `history: list[dict[str, Any]] = Field(default_factory=list)`
- Remove `build: str = "pending"` field
- Remove `review: str = "pending"` field
- Remove `prepare_phase: str = ""` field

Keep all other fields (`phase`, `kind`, `finalize`, `grounding`, `dor`, `artifacts`,
`audit`, `review_round`, etc.) — they serve independent purposes.

**Why:** `default_state()` returns `TodoState().model_dump(exclude_none=True)`, which is
used by `read_phase_state()` for deep-merge defaults. The model must produce v2 defaults
before migration can work correctly. Removing legacy fields from the model means new
state files are born as v2 and never include the legacy fields.

**Verification:** `default_state()` returns dict with `schema_version: 2`,
`current: "input_assessment"`, `history: []`, and without `build`, `review`, or
`prepare_phase` keys. Existing tests that construct TodoState directly should still work
since the model is more permissive (missing fields get defaults).

**Files:**

- Modified: `teleclaude/types/todos.py`

---

## Task 3: Add v1→v2 migration to read_phase_state

**What:** Modify `read_phase_state()` in `teleclaude/core/next_machine/state_io.py`:

1. After loading raw YAML, check `schema_version`:
   - If `2` → return the blob directly (self-contained, skip deep-merge with
     `default_state()`). Normalize `finalize` as today.
   - If `1` or absent → deep-merge with `default_state()` as today, then migrate.

2. Migration function `_migrate_v1_to_v2(state) -> dict`:
   - Derive `current` from legacy field combination using this precedence:
     - `finalize.status == "handed_off"` → `"finalize_handed_off"`
     - `finalize.status == "ready"` → `"finalize_ready"`
     - `review == "approved"` → `"review_approved"`
     - `review == "changes_requested"` → `"review_changes_requested"`
     - `review` in `("pending","started")` and `build == "complete"` → `"review_pending"`
     - `build == "complete"` → `"build_complete"`
     - `build == "started"` → `"build_started"`
     - `prepare_phase` is non-empty and valid → use that value directly
     - Fallback → `"input_assessment"`
   - Set `schema_version = 2`
   - Set `history = []` (no history reconstructable from v1)
   - Delete keys: `build`, `review`, `prepare_phase`
   - Return migrated dict

3. Also modify `write_phase_state()`: no changes needed — it's a simple YAML dump.
   The caller is responsible for passing v2 state.

**Why:** On-read migration means no batch script needed and running sessions transparently
upgrade. The precedence order (finalize → review → build → prepare) resolves ambiguity:
the furthest-progressed lifecycle phase wins. V2 blobs skipping deep-merge prevents
`default_state()` from reintroducing legacy field defaults.

**Verification:** Remove xfail markers and make GREEN:

- `test_read_phase_state_migrates_legacy_prepare_state_into_v2_current`
- `test_read_phase_state_keeps_existing_v2_blob_without_reintroducing_legacy_fields`

**Files:**

- Modified: `teleclaude/core/next_machine/state_io.py` (lines 201–237)

---

## Task 4: Migrate prepare machine to use `current`

**What:** Three sub-changes:

### 4a: Update prepare.py router (lines 100–116)

Replace the current phase resolution logic:

```python
# BEFORE: reads prepare_phase, falls back to _derive_prepare_phase
raw_phase = str(state.get("prepare_phase", "")).strip()
try:
    phase = PreparePhase(raw_phase)
except ValueError:
    phase = await asyncio.to_thread(_derive_prepare_phase, ...)
```

With:

```python
# AFTER: reads current directly
raw_current = str(state.get("current", "")).strip()
try:
    phase = PreparePhase(raw_current)
except ValueError:
    # current is a work-phase state (build_started, etc.) — prepare is done
    return "PREPARED: ..."
```

Also update `_apply_stale_artifact_reroute()` (lines 30–55) to write
`state["current"]` instead of `state["prepare_phase"]`.

### 4b: Update prepare_steps.py writes (~25 locations)

Replace all `state["prepare_phase"] = PreparePhase.X.value` with
`state["current"] = PreparePhase.X.value` throughout prepare_steps.py.
These are mechanical substitutions — the step function logic is unchanged.

### 4c: Remove \_derive_prepare_phase from runtime and update remaining writes

In `prepare_events.py`, `_derive_prepare_phase()` (lines 85–139) is no longer called
from the runtime path. Keep it only if the migration needs it (it doesn't — migration
maps from `prepare_phase` field value, not re-derivation). Also remove
`_is_artifact_produced()` (lines 57–66) — ghost artifact protection is no longer needed
since `current` is authoritative. The staleness check (`check_artifact_staleness`) using
digests remains — it's about content freshness, not lifecycle state.

Additionally, update `prepare_events.py` line 170 in `check_changed_paths_invalidation`:
replace `state["prepare_phase"] = PreparePhase.GROUNDING_CHECK.value` with
`state["current"] = PreparePhase.GROUNDING_CHECK.value`. This write is in the grounding
invalidation path, separate from `_derive_prepare_phase`, and must also switch to `current`.

**Why:** The prepare machine is the primary consumer of lifecycle state and the site of
most inference bugs (staleness loops, ghost artifact protection). Routing from `current`
eliminates `_derive_prepare_phase` and all its fallibility. Step functions writing
`current` directly is acceptable because they ARE the state machine implementation —
they know exactly what state they're transitioning to. External callers use the engine.

**Verification:** Remove xfail marker and make GREEN:

- `test_next_prepare_routes_from_current_without_phase_derivation`

Also verify: `prepare_events.py` no longer exports `_derive_prepare_phase` or
`_is_artifact_produced` from any runtime import path.

**Files:**

- Modified: `teleclaude/core/next_machine/prepare.py`
- Modified: `teleclaude/core/next_machine/prepare_steps.py`
- Modified: `teleclaude/core/next_machine/prepare_events.py`

---

## Task 5: Migrate work machine and readiness checks

**What:** Two sub-changes:

### 5a: Update is_ready_for_work in slug_resolution.py (lines 235–251)

Replace multi-field inference:

```python
# BEFORE: phase + build + dor.score
phase = state.get("phase")
build = state.get(PhaseName.BUILD.value)
dor = state.get("dor")
...
```

With `current`-based check:

```python
# AFTER: current == "prepared" means ready
current = state.get("current", "")
return current == "prepared"
```

Keep the DOR score ≥ 8 check as an additional guard, or rely solely on `current`
reaching `"prepared"` (which already requires DOR gate passage). The test spec
asserts `current == "prepared" → True` and `current == "requirements_review" → False`,
so the check is on `current` alone.

Also update `get_item_phase()` to derive from `current` if needed, and
`set_item_phase()` to update `phase` field (which is the coarse-grained pending/
in_progress/done marker, separate from `current`).

### 5b: Update work.py dispatch

Modify `next_work()` precondition checks to read `state["current"]` instead of
`state[PhaseName.BUILD.value]` for determining work status.

Replace `mark_phase()` calls in work.py (4 locations):

- Line 522: `mark_phase(BUILD, COMPLETE)` → fire `"complete_build"` transition
- Line 558: `mark_phase(REVIEW, PENDING)` → fire `"start_review"` transition
- Line 773: `mark_phase(BUILD, STARTED)` → fire `"start_build"` transition
- Line 841: `_mark_finalize_handed_off()` → fire `"finalize_handoff"` transition

These require instantiating a work lifecycle `StateMachine` with appropriate states
and transitions. Define a module-level factory or constant for the work machine
definition (states ordered: `prepared`, `build_started`, `build_complete`,
`review_pending`, `review_changes_requested`, `review_approved`, `finalize_ready`,
`finalize_handed_off`).

**Why:** The work machine currently uses `mark_phase()` for state mutations, which
patches individual fields. Routing through the engine ensures atomic transitions with
history recording. The `is_ready_for_work` simplification from multi-field inference to
`current == "prepared"` eliminates the entire class of "ready but not really" bugs.

**Verification:** Remove xfail marker and make GREEN:

- `test_is_ready_for_work_uses_current_authoritative_state_value`

**Files:**

- Modified: `teleclaude/core/next_machine/slug_resolution.py`
- Modified: `teleclaude/core/next_machine/work.py`

---

## Task 6: Convert mark-\* functions to v2 wrappers

**What:** Update mark operations in `teleclaude/core/next_machine/state_io.py`:

### mark_phase (lines 253–291)

Read v2 state, map `(phase, status)` to transition name, fire through engine, write
result. Mapping:

- `(build, started)` → `"start_build"`
- `(build, complete)` → `"complete_build"`
- `(review, pending)` → `"start_review"`
- `(review, approved)` → `"approve_review"`
- `(review, changes_requested)` → `"request_changes"`

Preserve the review-round increment, finding-tracking, and baseline-commit logic as
transition actions or post-transition side effects.

### mark_prepare_phase (lines 321–357)

Read v2 state, set `state["current"]` to the given prepare phase value, write. When
status is `"prepared"`, also stamp grounding as today.

### mark_prepare_verdict (lines 294–318)

No change to `current` — verdicts are metadata stored in `requirements_review`/
`plan_review`/`test_spec_review` sub-dicts. The verdict write doesn't change lifecycle
state; it's consumed by the prepare router's next iteration.

### mark_finalize_ready (lines 360–408)

Fire `"finalize_ready"` transition. Preserve validation (worktree exists, no uncommitted
changes, branch pushed).

### mark_ready (lines 594–684)

Fire a transition directly to `"prepared"` state, skipping prepare lifecycle. Set
`current = "prepared"` and write appropriate history entry.

### \_mark_finalize_handed_off (lines 411–429)

Fire `"finalize_handoff"` transition.

**Why:** Mark-\* functions are the primary mutation API used by CLI and work machine.
Routing through the engine ensures all state changes produce history entries and respect
guards. The wrappers maintain the same external interface so existing callers (CLI routes,
work.py) continue to work during migration. After Task 5 converts work.py to use
`fire()` directly, these wrappers serve as backward-compatible CLI/API entry points.

**Verification:** Existing mark-\* tests should continue passing — observable behavior
(state file written with correct values) is unchanged. History entries are a new
observable that can be verified by reading state after mark operations.

**Files:**

- Modified: `teleclaude/core/next_machine/state_io.py`

---

## Task 7: Update display and validation consumers

**What:** Update all remaining consumers of legacy fields:

### roadmap.py (lines 99–117)

Replace `state.get("build")` and `state.get("review")` with derivation from `current`:

- Map `current` to build/review status for display purposes
- Or read `current` directly and render a unified status column
- Update `_derive_phase_status()` (line 154) which takes `build_status` as parameter
- Update `TodoInfo` construction (lines 127–128, 183–184, 201–202) to derive
  `build_status` and `review_status` from `current` instead of raw state fields

### core/models/\_snapshot.py (TodoInfo dataclass)

`TodoInfo` (line 251) carries `build_status` and `review_status` attrs that flow
through the DTO pipeline. These fields must either be derived from `current` at
construction time (in `roadmap.py`) or replaced with a `current` field. The downstream
chain:

- `api_models.py:201–244`: `TodoDTO.from_info()` maps `TodoInfo.build_status` →
  `TodoDTO.build_status`
- `core/cache.py:493–494`: reads `todo.build_status` and `todo.review_status`

The simplest approach: keep `build_status`/`review_status` as derived display fields
on `TodoInfo` (backward-compatible for TUI/API consumers) but source them from
`current` during construction in `roadmap.py`. No changes needed in `api_models.py`
or `cache.py` if the `TodoInfo` contract stays stable.

### todo_row.py (lines 223–319)

The TUI widget reads `build_status`, `review_status`, `prepare_phase` from a DTO.
Update to read `current` and derive display labels. The prepare phase label function
`prepare_phase_label()` already maps phase strings — extend it to handle work states
or use `current` directly.

### resource_validation/**init**.py (line 594)

Replace `state.build == "pending"` with `current`-based check.

### output_formatting.py

Update any guidance strings that reference `mark-phase` or `mark-ready` to reference
`telec todo state`.

### todo_scaffold.py

- Line 207: `child_state["prepare_phase"] = inherited_phase` →
  `child_state["current"] = inherited_phase`
- Line 347: `state["prepare_phase"] = ""` →
  `state["current"] = "input_assessment"`

**Why:** Display and validation consumers must read v2 format after migration is active.
Without these updates, roadmap listing, TUI display, and resource validation would fail
on missing `build`/`review` keys. The DTO pipeline (`TodoInfo` → `TodoDTO` → TUI/API)
must source `build_status`/`review_status` from `current` rather than from removed
legacy fields.

**Verification:** Run `telec roadmap list` and verify display renders correctly. TUI
todo rows should show lifecycle state from `current`. Resource validation should not
reject valid states. No test specs were delivered for display consumer behavior — the
test spec phase approved coverage for engine, migration, routing, readiness, and CLI.
Display consumers are verified manually and through existing characterization tests
for `roadmap.py` and `todo_row.py` if they exist. The code reviewer should evaluate
whether additional characterization tests are warranted.

**Files:**

- Modified: `teleclaude/core/roadmap.py`
- Modified: `teleclaude/core/models/_snapshot.py` (if `TodoInfo` needs `current` field)
- Modified: `teleclaude/cli/tui/widgets/todo_row.py`
- Modified: `teleclaude/resource_validation/__init__.py`
- Modified: `teleclaude/core/next_machine/output_formatting.py`
- Modified: `teleclaude/todo_scaffold.py`

---

## Task 8: Add CLI command surface and API route

**What:** Two sub-changes:

### 8a: CLI surface definition

Add `state` subcommand to `CLI_SURFACE["todo"]` in `teleclaude/cli/telec/surface.py`:

- `args: "<slug> [<transition>]"`
- Flags: `--rewind` (boolean)
- Description: "Inspect state, fire transition, or rewind"

Add routing in `teleclaude/cli/telec/handlers/todo.py`:

- `"state"` subcommand routes to `handle_todo_state`

### 8b: CLI handler

Add `handle_todo_state(args)` in `teleclaude/cli/tool_commands/todo.py`:

- Parse args: slug (required), transition (optional positional), --rewind flag
- Call `tool_api_call("POST", "/todos/state", json_body={...})`
- Print JSON response

### 8c: API route

Add `POST /todos/state` handler in `teleclaude/api/todo_routes.py`:

- Body: `{slug, cwd, transition?, rewind?}`
- If only slug + cwd → return current state snapshot with valid transitions
- If transition provided → fire transition through engine, return updated state
- If rewind → rewind through engine, return updated state
- Add appropriate clearance control

**Why:** `telec todo state` is the primary agent-facing interface for state inspection
and manipulation. It replaces the need for agents to know which mark-_ command to use
for each lifecycle transition. The unified API route consolidates multiple mark-_ routes
into one.

**Verification:** Remove xfail markers and make GREEN:

- `test_handle_todo_state_reads_current_snapshot_when_only_slug_is_provided`
- `test_handle_todo_state_fires_a_named_transition`
- `test_handle_todo_state_requests_rewind`
- `test_todo_surface_exposes_state_subcommand_with_rewind_flag`
- `test_handle_todo_routes_state_subcommand_to_tool_command_handler`

**Files:**

- Modified: `teleclaude/cli/telec/surface.py`
- Modified: `teleclaude/cli/telec/handlers/todo.py`
- Modified: `teleclaude/cli/tool_commands/todo.py`
- Modified: `teleclaude/api/todo_routes.py`

---

## Task 9: NFR-1 sweep and agent artifact updates

**What:**

### 9a: Grep sweep

Run comprehensive grep to verify no remaining runtime references to:

- `state["build"]` or `state.get("build")` outside migration code
- `state["review"]` or `state.get("review")` outside migration code
- `state["prepare_phase"]` or `state.get("prepare_phase")` outside migration code
- `_derive_prepare_phase` imports or calls outside test characterization
- `_is_artifact_produced` imports or calls
- `produced_at` used as state proxy (vs. artifact metadata)

Fix any remaining references found.

### 9b: Agent artifact updates

Update agent command artifacts under `agents/commands/` and skills that reference:

- `mark-phase` → add reference to `telec todo state`
- `mark-ready` → mention as wrapper, recommend `telec todo state`
- `mark-finalize-ready` → same

Update CLI help text in `CLI_SURFACE` dict for affected commands.

### 9c: Doc snippet updates

If any doc snippets reference the old state model (lifecycle-state-machines,
prepare-state-machine, work-state-machine), note them for follow-up update. Do not
modify doc snippets in this task — they have their own authoring procedure.

**Why:** NFR-1 requires zero inference-based state reads after delivery. The grep sweep
is the enforcement mechanism. Agent artifacts that reference mark-\* commands will
mislead agents if not updated.

**Verification:**

- Grep sweep produces zero matches outside migration code, tests, and documentation
- Pre-commit hooks pass (lint, typecheck, tests)
- `telec todo state <slug>` works end-to-end

**Files:**

- Modified: Agent artifacts under `agents/commands/` (as needed)
- Modified: CLI help text in `teleclaude/cli/telec/surface.py` (as needed)

---

## Cross-cutting concerns

### History entry format

All history entries use this shape:

```python
{
    "source": str,      # state before transition
    "target": str,      # state after transition
    "transition": str,  # transition name
    "at": str,          # ISO 8601 timestamp
    "by": str,          # actor session ID
    "metadata": dict,   # transition-specific (verdict, digest, etc.)
}
```

### Work lifecycle states (ordered)

```
prepared → build_started → build_complete → review_pending →
review_changes_requested → review_approved → finalize_ready →
finalize_handed_off
```

The `review_changes_requested → build_started` cycle is handled by the transition
source-set check taking priority over the ordered-index past check.

### Prepare lifecycle states (from PreparePhase enum)

No change to the enum values. `current` uses the same string values as `PreparePhase`.

### Logging

Log at INFO level for all transition fires (source, target, actor, slug).
Log at WARNING for rejected transitions and failed rewinds.
