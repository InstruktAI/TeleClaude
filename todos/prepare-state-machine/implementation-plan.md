# Implementation Plan: prepare-state-machine

## Overview

Rewrite `next_prepare()` from a linear if/else chain into a deterministic state
machine with durable checkpoints, modeled on the integration state machine pattern.
Ten ordered tasks, each a commit-worthy unit.

The approach reuses the proven integration pattern: a `PreparePhase` enum defines
all states, a dispatch loop reads durable state and calls per-phase handlers, each
handler returns `tuple[bool, str]` to either loop or return an instruction. State
is persisted in the existing `state.yaml` via `DEFAULT_STATE` merge, ensuring
backward compatibility without a separate checkpoint file.

---

## Task 1: Define PreparePhase Enum and Constants

**What:** Add `PreparePhase(str, Enum)` to `teleclaude/core/next_machine/core.py`
(near the existing `PhaseName`, `PhaseStatus`, and `ItemPhase` enums at lines 42-74).
Define all 10 states: `INPUT_ASSESSMENT`, `TRIANGULATION`, `REQUIREMENTS_REVIEW`,
`PLAN_DRAFTING`, `PLAN_REVIEW`, `GATE`, `GROUNDING_CHECK`, `RE_GROUNDING`,
`PREPARED`, `BLOCKED`. Add a `_PREPARE_LOOP_LIMIT = 20` constant (matching the
integration pattern's safety cap style at `state_machine.py:46`).

**Why:** The enum is the foundation that all subsequent tasks reference. Defining it
first lets the type system guide the dispatcher and handler implementations. The loop
limit is a safety cap against infinite cycling during development of the dispatch loop.

**Verification:**
- Unit test in `tests/unit/test_prepare_state_machine.py` confirming all 10 enum
  values exist, are string-typed, and have the expected `.value` strings.
- `python -c "from teleclaude.core.next_machine.core import PreparePhase; print(list(PreparePhase))"` succeeds.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 42-74 for placement)
- `teleclaude/core/integration/state_machine.py` (lines 57-74 for pattern)

**Covers:** R1

---

## Task 2: Extend DEFAULT_STATE and State I/O for Grounding and Review Sections

**What:** Extend `DEFAULT_STATE` (core.py:799-810) with new default keys:

```python
"grounding": {
    "valid": False,
    "base_sha": "",
    "input_digest": "",
    "referenced_paths": [],
    "last_grounded_at": "",
    "invalidated_at": "",
    "invalidation_reason": "",
},
"requirements_review": {
    "verdict": "",
    "reviewed_at": "",
    "findings_count": 0,
},
"plan_review": {
    "verdict": "",
    "reviewed_at": "",
    "findings_count": 0,
},
"prepare_phase": "",
```

The existing `read_phase_state()` / `write_phase_state()` (core.py:818-858) already
merge with `DEFAULT_STATE` via `{**DEFAULT_STATE, **state}`, so new sections
automatically get sensible defaults for legacy state files. No changes needed to the
I/O functions themselves.

Add a `prepare_phase` top-level key to `DEFAULT_STATE` (empty string = not started).
This is the durable checkpoint for the prepare state machine, persisted alongside
existing build/review state.

**Why:** Durable state is the backbone of crash recovery and idempotent re-entry.
Using `DEFAULT_STATE` merge ensures backward compatibility: existing state.yaml files
without these sections load cleanly with defaults. This matches the integration
pattern's checkpoint approach (state_machine.py:119-157) but reuses the existing
YAML-based state.yaml rather than introducing a separate JSON checkpoint file.

**Builder note (from review F2):** The `{**DEFAULT_STATE, **state}` merge is shallow.
If a partial `grounding` section exists (e.g. `grounding: {valid: true}` with no
`base_sha`), the sub-keys will be missing. Step handlers reading nested sections
should apply sub-key defaulting: `{**DEFAULT_STATE["grounding"], **state.get("grounding", {})}`.

**Verification:**
- Round-trip test: write state with all new sections, read back, all fields preserved.
- Backward compatibility test: state.yaml without new sections loads with sensible
  defaults (empty strings, False, 0, empty lists).
- Existing `test_read_phase_state_returns_default_when_no_file` still passes with new
  keys present in the output.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 795-858 for DEFAULT_STATE and I/O)
- `teleclaude/core/integration/state_machine.py` (lines 76-93, 119-184 for checkpoint pattern)

**Covers:** R3

---

## Task 3: Build the Step Dispatcher and Dispatch Loop

**What:** Replace the body of `next_prepare()` (core.py:2406-2577) with:

1. **Pre-dispatch preconditions** (before the loop): slug resolution, roadmap
   validation, container detection. These are not phases -- they are preconditions,
   matching the integration pattern where slug selection happens before
   `_dispatch_sync()` (state_machine.py:553-600).

2. **Dispatch loop**: Read `prepare_phase` from state.yaml via `read_phase_state()`.
   If empty or unrecognized, derive the initial phase from artifact existence
   (input.md, breakdown state, requirements.md, implementation-plan.md, DOR score).
   Call `_prepare_step()` which dispatches to `_prepare_step_<phase>()` handlers.
   Each handler returns `tuple[bool, str]` -- `(continue_loop, instruction)`.
   Loop until a handler returns `(False, instruction)` or `_PREPARE_LOOP_LIMIT`
   is reached.

3. **Signature change**: Remove the `hitl` parameter. New signature:
   ```python
   async def next_prepare(db: Db, slug: str | None, cwd: str) -> str
   ```

4. **Stub handlers**: Each `_prepare_step_<phase>()` initially returns
   `(False, "NOT_IMPLEMENTED: <phase>")`. This lets the dispatcher compile and
   pass tests before individual handlers are fleshed out.

The dispatcher function `_prepare_step()` follows the exact pattern of
`_step()` in `state_machine.py:603-702`: a chain of `if phase == ...` checks
dispatching to individual handler functions.

**Why:** Building the skeleton first -- with stub handlers -- ensures the dispatch
loop architecture is correct before adding business logic. This is the same
build order used for the integration state machine. The `hitl` removal happens
here because the signature change must be atomic with the implementation change.

**Verification:**
- `next_prepare(db, slug, cwd)` compiles (no `hitl` parameter).
- Calling with a valid slug hits the dispatch loop and returns a stub instruction.
- Loop limit test: force a handler to return `(True, "")` repeatedly, verify the
  function returns a LOOP_LIMIT error.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 2406-2577 for current implementation)
- `teleclaude/core/integration/state_machine.py` (lines 553-702 for dispatch pattern)

**Covers:** R2 (architecture), R10 (hitl removal -- signature)

---

## Task 4: Implement Phase Handlers -- INPUT_ASSESSMENT through TRIANGULATION

**What:** Implement two handlers in `teleclaude/core/next_machine/core.py`:

- `_prepare_step_input_assessment(slug, cwd, state)`: Checks if breakdown has been
  assessed. If yes, writes `prepare_phase = TRIANGULATION` to state, returns
  `(True, "")` to loop. If no, returns `(False, format_tool_call(...))` dispatching
  `next-prepare-draft` with a note to assess input.md.

- `_prepare_step_triangulation(db, slug, cwd, state)`: Checks if `requirements.md`
  exists. If yes, writes `prepare_phase = REQUIREMENTS_REVIEW`, returns `(True, "")`.
  If no, returns `(False, format_tool_call(...))` dispatching `next-prepare-draft`
  with a note to derive requirements from input.md.

Phase derivation at loop entry: if `prepare_phase` is empty, derive it:
- input.md exists + breakdown not assessed -> `INPUT_ASSESSMENT`
- input.md exists + breakdown assessed + no requirements.md -> `TRIANGULATION`
- requirements.md exists + no review verdict -> `REQUIREMENTS_REVIEW`
- requirements.md exists + approved + no plan -> `PLAN_DRAFTING`
- plan exists + no review verdict -> `PLAN_REVIEW`
- plan approved + no DOR gate -> `GATE`
- DOR passed -> `GROUNDING_CHECK`
- Otherwise fallback to `INPUT_ASSESSMENT`

This derivation allows existing todos (which have no `prepare_phase` in state.yaml)
to enter the machine at the correct point.

**Why:** These are the first two phases in the lifecycle. Implementing them together
makes sense because INPUT_ASSESSMENT always transitions to TRIANGULATION. The phase
derivation logic replaces the existing linear if/else chain and handles legacy todos.

**Verification:**
- Unit test: state with unassessed breakdown -> INPUT_ASSESSMENT -> dispatches assessment.
- Unit test: state with assessed breakdown, no requirements.md -> TRIANGULATION ->
  dispatches requirements drafting.
- Unit test: state with assessed breakdown, requirements.md exists -> transitions to
  REQUIREMENTS_REVIEW (loop continues).

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 2484-2525 for current breakdown/requirements logic)

**Covers:** R2 (handlers), R4 (INPUT_ASSESSMENT and TRIANGULATION transitions)

---

## Task 5: Implement Phase Handlers -- REQUIREMENTS_REVIEW and PLAN_DRAFTING

**What:** Implement two handlers:

- `_prepare_step_requirements_review(db, slug, cwd, state)`: Reads
  `state["requirements_review"]["verdict"]`.
  - If `"approve"`: writes `prepare_phase = PLAN_DRAFTING`, returns `(True, "")`.
  - If `"needs_work"`: writes `prepare_phase = TRIANGULATION` (loop-back), clears
    the verdict, returns `(True, "")`. The next TRIANGULATION dispatch includes the
    review findings as a note.
  - If empty (no verdict yet): returns `(False, format_tool_call(...))` dispatching
    `next-review-requirements` with the slug. This sends the reviewer to evaluate
    requirements.md and write its verdict to state.yaml.

- `_prepare_step_plan_drafting(db, slug, cwd, state)`: Checks if
  `implementation-plan.md` exists.
  - If yes: writes `prepare_phase = PLAN_REVIEW`, returns `(True, "")`.
  - If no: returns `(False, format_tool_call(...))` dispatching `next-prepare-draft`
    to write the implementation plan.

The `needs_work` loop-back dispatches with findings attached, not a fresh dispatch.
Read `todos/<slug>/requirements-review-findings.md` to attach findings to the note
field of `format_tool_call()`.

**Why:** The review dispatch (R6) is implemented here as part of the natural phase
flow. The REQUIREMENTS_REVIEW handler is the first consumer of the review verdict
from state.yaml (R3). The loop-back with findings enables targeted fixes rather
than starting from scratch.

**Verification:**
- Unit test: REQUIREMENTS_REVIEW with no verdict -> dispatches `next-review-requirements`.
- Unit test: REQUIREMENTS_REVIEW with `approve` -> transitions to PLAN_DRAFTING.
- Unit test: REQUIREMENTS_REVIEW with `needs_work` -> transitions back to TRIANGULATION.
- Unit test: PLAN_DRAFTING with no plan -> dispatches `next-prepare-draft`.
- Unit test: PLAN_DRAFTING with plan exists -> transitions to PLAN_REVIEW.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 2527-2543 for current plan check)

**Covers:** R4 (REQUIREMENTS_REVIEW, PLAN_DRAFTING transitions), R6 (review dispatch)

---

## Task 6: Implement Phase Handlers -- PLAN_REVIEW, GATE, and Terminal States

**What:** Implement four handlers:

- `_prepare_step_plan_review(db, slug, cwd, state)`: Same structure as
  `_prepare_step_requirements_review` but reads `state["plan_review"]["verdict"]`.
  - Approve -> `GATE`.
  - Needs work -> `PLAN_DRAFTING` (loop-back with findings).
  - No verdict -> dispatches `next-review-plan`.

- `_prepare_step_gate(db, slug, cwd, state)`: Reads DOR score from
  `state.get("dor", {}).get("score")`.
  - Score >= `DOR_READY_THRESHOLD` (8) -> writes `prepare_phase = GROUNDING_CHECK`,
    calls `sync_main_to_worktree()`, returns `(True, "")`.
  - Score < 8 or no score -> dispatches `next-prepare-gate` to run DOR assessment.
    The gate worker re-assesses and updates the score. Single threshold, matching
    the existing `DOR_READY_THRESHOLD` pattern.

- `_prepare_step_prepared(slug, state)`: Terminal. Returns
  `(False, format_prepared(slug))`.

- `_prepare_step_blocked(slug, state)`: Terminal. Returns
  `(False, "BLOCKED: <slug> requires human decision. ...")`.

**Why:** These complete the happy path (PLAN_REVIEW -> GATE -> terminal) and the
failure path (GATE -> BLOCKED). The DOR threshold logic is lifted directly from
the existing implementation (core.py:2545-2575).

**Verification:**
- Unit test: PLAN_REVIEW with no verdict -> dispatches `next-review-plan`.
- Unit test: PLAN_REVIEW approve -> transitions to GATE.
- Unit test: PLAN_REVIEW needs_work -> transitions to PLAN_DRAFTING.
- Unit test: GATE with score >= 8 -> transitions to GROUNDING_CHECK.
- Unit test: GATE with score < 8 -> dispatches `next-prepare-gate`.
- Unit test: GATE with no score -> dispatches `next-prepare-gate`.
- Unit test: PREPARED returns terminal instruction.
- Unit test: BLOCKED returns terminal instruction.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 2545-2577 for current DOR logic)

**Covers:** R4 (PLAN_REVIEW, GATE, PREPARED, BLOCKED transitions), R6 (plan review dispatch)

---

## Task 7: Implement GROUNDING_CHECK and RE_GROUNDING Phases

**What:** Implement two handlers:

- `_prepare_step_grounding_check(slug, cwd, state)`: Performs deterministic,
  non-agent comparison:
  1. Read `state["grounding"]["base_sha"]` and compare against current
     `git rev-parse HEAD` (via `subprocess.run`).
  2. Read `state["grounding"]["input_digest"]` and compare against current
     `hashlib.sha256(input.md contents)`.
  3. Read `state["grounding"]["referenced_paths"]` and check if any were modified
     between `base_sha` and current HEAD via `git diff --name-only <base_sha>..HEAD`.
  4. If all match: write `prepare_phase = PREPARED`, return `(True, "")`.
  5. If any differ: write `prepare_phase = RE_GROUNDING`, record the diff in
     `state["grounding"]`, return `(True, "")`.
  6. If `base_sha` is empty (first grounding): capture current HEAD, input digest,
     and referenced paths; write to state; transition to PREPARED.

- `_prepare_step_re_grounding(db, slug, cwd, state)`: Dispatches agent to update
  the implementation plan against the changed files. Returns
  `(False, format_tool_call(...))` with `next-prepare-draft` and a note listing
  the changed referenced paths. Write `prepare_phase = PLAN_REVIEW` before
  dispatching so the next call enters at the right point (re-grounded plan must
  be reviewed before proceeding).

The grounding check is purely mechanical -- no agent dispatch, sub-second execution.
Git operations use `subprocess.run` (same pattern as existing
`resolve_canonical_project_root` at core.py:1222).

**Why:** The grounding check (R7) is the freshness mechanism that prevents building
on stale artifacts. It must be mechanical (no agent) for speed and determinism.
RE_GROUNDING dispatches back through PLAN_REVIEW to ensure the updated plan gets
reviewed before proceeding.

**Verification:**
- Unit test: mocked git ops, all matching -> transitions to PREPARED.
- Unit test: mocked git ops, SHA differs -> transitions to RE_GROUNDING.
- Unit test: mocked git ops, referenced path changed -> transitions to RE_GROUNDING.
- Unit test: empty base_sha (first run) -> captures grounding state, transitions to PREPARED.
- Unit test: RE_GROUNDING dispatches `next-prepare-draft` with changed paths note.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (hashlib already imported at line 12)

**Covers:** R7 (grounding check), R4 (GROUNDING_CHECK and RE_GROUNDING transitions)

---

## Task 8: Wire Event Emission into Phase Transitions

**What:** Add a `_emit_prepare_event(event_type, payload)` helper function in
`core.py`, following the fire-and-forget pattern from integration
(state_machine.py:533-545). Use the event bridge (lazy-imported from
`teleclaude.core.integration_bridge`) to dispatch events without blocking.

Insert event emission calls at each phase transition point identified in R4:

| Transition | Event Type |
|---|---|
| -> TRIANGULATION (from entry) | `domain.software-development.prepare.triangulation_started` |
| -> REQUIREMENTS_REVIEW | `domain.software-development.prepare.requirements_drafted` |
| -> PLAN_DRAFTING (from approve) | `domain.software-development.prepare.requirements_approved` |
| -> PLAN_REVIEW (from plan written) | `domain.software-development.prepare.plan_drafted` |
| -> GATE (from approve) | `domain.software-development.prepare.plan_approved` |
| -> RE_GROUNDING | `domain.software-development.prepare.grounding_invalidated` |
| -> PLAN_REVIEW (from regrounding) | `domain.software-development.prepare.regrounded` |
| -> PREPARED (terminal) | `domain.software-development.prepare.completed` |
| -> BLOCKED | `domain.software-development.prepare.blocked` |

All events include `slug` in payload. `grounding_invalidated` adds `reason` and
`changed_paths`. `blocked` adds `blocker`.

**Why:** Events are observability and notification hooks. Emitting them at transition
points rather than inside handlers keeps the handlers focused on state logic. The
fire-and-forget pattern ensures event emission never blocks the state machine.

**Verification:**
- Unit test: mock the event emission function, trigger each transition, assert correct
  event type and payload.
- Verify event types match the registered schemas in `software_development.py:194-300`.

**Referenced files:**
- `teleclaude_events/schemas/software_development.py` (lines 194-300)
- `teleclaude/core/integration/state_machine.py` (lines 499-545)

**Covers:** R5

---

## Task 9: CLI Changes -- Remove hitl, Add invalidate-check Flag

**What:** Five changes across CLI, API, and completions:

1. **Remove `--no-hitl` from `handle_todo_prepare()`** (tool_commands.py:736-774):
   Remove the `--no-hitl` flag parsing and the `hitl` key from the request body.
   Update the docstring to remove `--no-hitl` from usage.

2. **Remove `--no-hitl` from CLI_SURFACE** (telec.py:519): Remove the
   `Flag("--no-hitl", ...)` entry from the `prepare` command definition.

3. **Remove `--no-hitl` from completions allowlist** (telec.py:1092): Remove
   `"--no-hitl"` from the set of known boolean flags.

4. **Add `--invalidate-check` and `--changed-paths` flags**:
   - In `handle_todo_prepare()`: when `--invalidate-check` is present, call a new
     function `invalidate_stale_preparations(cwd, changed_paths)` directly (no API
     call -- this is a local mechanical operation).
   - The function scans all active (non-icebox, non-delivered) todos via
     `load_roadmap_slugs()`, reads each state.yaml's `grounding.referenced_paths`,
     checks for overlap with `changed_paths`, and if found: sets
     `grounding.valid = false`, `invalidated_at = now()`,
     `invalidation_reason = "files_changed"`.
   - Emits `prepare.grounding_invalidated` event for each invalidated slug.
   - Returns JSON with `{"invalidated": ["slug-a", "slug-b"]}`.
   - In CLI_SURFACE: add `Flag("--invalidate-check", ...)` and
     `Flag("--changed-paths", desc="Comma-separated file paths", value_name="PATHS")`.

5. **Update API endpoint** (todo_routes.py:51-66): Remove the `hitl` parameter
   from the `todo_prepare` endpoint. Update the call to `next_prepare(db, slug, cwd)`.

**Why:** The `hitl` removal must touch all call sites simultaneously to avoid
signature mismatches. The `--invalidate-check` flag is a pure CLI addition designed
for post-commit hooks -- it does not go through the API because it is a local
mechanical operation that must execute in sub-second time.

**Verification:**
- `telec todo prepare --help` shows no `--no-hitl`, shows `--invalidate-check` and
  `--changed-paths`.
- Grep for `hitl` in `teleclaude/cli/`, `teleclaude/api/`,
  `teleclaude/core/next_machine/` -- zero occurrences.
- Unit test: `--invalidate-check --changed-paths src/foo.py` with a todo that has
  `referenced_paths: ["src/foo.py"]` -> `grounding.valid` set to false.
- Unit test: `--changed-paths unrelated.py` -> no invalidation.

**Referenced files:**
- `teleclaude/cli/tool_commands.py` (lines 736-774)
- `teleclaude/cli/telec.py` (lines 515-522, 1085-1093)
- `teleclaude/api/todo_routes.py` (lines 51-66)

**Covers:** R8 (CLI invalidation check), R10 (hitl removal -- CLI, API, all callers)

---

## Task 10: Pre-Build Freshness Gate and Test Rewrite

**What:** Two parallel efforts:

### 10a: Pre-build freshness gate in next_work

Add a pre-flight check at the beginning of `next_work()` (core.py:2582+), after
slug resolution but before worktree preparation:

```python
# Pre-build freshness gate: verify preparation is still valid
prep_state = await asyncio.to_thread(read_phase_state, cwd, resolved_slug)
grounding = prep_state.get("grounding", {})
if isinstance(grounding, dict) and grounding.get("valid") is False:
    # Re-ground before building
    return (
        f"STALE: {resolved_slug} preparation is invalidated. "
        f"Run telec todo prepare {resolved_slug} to re-ground."
    )
```

This is a lightweight check -- it reads from state.yaml. The full grounding
logic runs inside `next_prepare()` when the orchestrator follows the returned
instruction.

**Builder note (from review F4):** Check `prepare_phase == "prepared"` instead of
(or in addition to) `grounding.valid`. Legacy todos without a `grounding` section
would have `grounding.valid = False` from `DEFAULT_STATE`, causing false-positive
blocks. The `prepare_phase` check avoids this migration edge case.

### 10b: Rewrite test suites

Rewrite the following test files for the new state machine architecture:

**`tests/unit/test_next_machine_hitl.py`** -- Remove all `hitl=True/False` tests.
Replace with tests for each PreparePhase handler:
- `test_prepare_no_slug_returns_tool_call` (replaces `test_next_prepare_hitl_no_slug`)
- `test_prepare_missing_requirements_dispatches_draft` (replaces `test_next_prepare_hitl_missing_requirements`)
- `test_prepare_missing_plan_dispatches_draft` (replaces `test_next_prepare_hitl_missing_impl_plan`)
- `test_prepare_both_exist_dispatches_gate` (replaces `test_next_prepare_hitl_both_exist`)
- `test_prepare_slug_missing_from_roadmap` (replaces `test_next_prepare_hitl_slug_missing_from_roadmap`)
- New: `test_prepare_requirements_review_approve_transitions_to_plan`
- New: `test_prepare_requirements_review_needs_work_loops_back`
- New: `test_prepare_plan_review_approve_transitions_to_gate`
- New: `test_prepare_plan_review_needs_work_loops_back`
- New: `test_prepare_gate_pass_transitions_to_grounding`
- New: `test_prepare_gate_fail_transitions_to_blocked`
- New: `test_prepare_grounding_check_fresh_transitions_to_prepared`
- New: `test_prepare_grounding_check_stale_transitions_to_regrounding`
- New: `test_prepare_regrounding_dispatches_draft_with_changes`
- New: `test_prepare_event_emission_at_transitions`
- New: `test_prepare_loop_limit_returns_error`

**`tests/unit/test_next_machine_breakdown.py`** -- Remove `hitl=True/False` from
all calls. The breakdown tests remain structurally similar but call
`next_prepare()` without the `hitl` parameter.

**`tests/unit/test_prepare_state_machine.py`** (new) -- Enum validation, state
schema round-trip, and invalidation-check tests.

Update any other test files that import or call `next_prepare` with `hitl`.

**Why:** The pre-build gate (R9) is a single check at the `next_work` call site.
The test rewrite is the highest-churn task and benefits from being last -- all
handlers are implemented and stable by this point.

**Verification:**
- Integration test: PREPARED todo with `grounding.valid = False` -> `next_work`
  returns stale instruction instead of build dispatch.
- All rewritten tests pass:
  `pytest tests/unit/test_next_machine_hitl.py tests/unit/test_next_machine_breakdown.py tests/unit/test_prepare_state_machine.py -v`
- Full test suite: `make test` passes with no regressions.
- Grep for `hitl` in test files calling `next_prepare` -- zero occurrences.
- No lint violations: `make lint` passes.

**Referenced files:**
- `teleclaude/core/next_machine/core.py` (lines 2582+ for next_work)
- `tests/unit/test_next_machine_hitl.py` (full rewrite)
- `tests/unit/test_next_machine_breakdown.py` (hitl removal)
- `tests/unit/test_prepare_state_machine.py` (new)

**Covers:** R9 (pre-build freshness gate), R2/R4/R10 (test coverage for all requirements)

---

## Requirement Coverage Matrix

| Requirement | Task(s) | Verification |
|---|---|---|
| R1: PreparePhase Enum | Task 1 | Enum test |
| R2: State Machine Architecture | Tasks 3, 4, 5, 6, 7 | Dispatcher test, handler tests |
| R3: Durable State in state.yaml | Task 2 | Round-trip test, backward compat test |
| R4: Phase Transitions | Tasks 4, 5, 6, 7 | Per-transition edge tests |
| R5: Event Emission | Task 8 | Mocked event emission tests |
| R6: Review Dispatch Commands | Tasks 5, 6 | Tool-call assertion tests |
| R7: Grounding Check | Task 7 | Mocked git operation tests |
| R8: CLI Invalidation Check Flag | Task 9 | CLI flag test, invalidation test |
| R9: Pre-Build Freshness Gate | Task 10a | Integration test with stale grounding |
| R10: Remove hitl Parameter | Tasks 3, 9, 10b | Grep zero-occurrence test |

## Risk Mitigations

- **Test churn (high):** Task 10b is last so all handlers are stable. The test
  rewrite follows the new architecture rather than patching old tests.
- **Caller contract change:** Task 9 removes `hitl` from all callers in a single
  commit. Grep verification catches missed sites.
- **Git operation failures:** Task 7 handles missing `base_sha` (first run) and
  invalid SHAs (fallback to PREPARED with a warning log).
- **Backward compatibility:** Task 2 uses `DEFAULT_STATE` merge, which is already
  the established pattern for schema evolution.
