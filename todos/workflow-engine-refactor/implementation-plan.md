# Implementation Plan: workflow-engine-refactor

## Overview

Replace the bespoke prepare and work state machines in
`teleclaude/core/next_machine/core.py` (4200 lines) with a configurable workflow
engine that interprets YAML workflow definitions. The engine reads `state.yaml`,
resolves the current step, and emits the same fully-specified dispatch
instructions the current hand-coded handlers produce. Pure refactoring —
behavioral equivalence is the acceptance criterion.

**Scope reduction from prior review (C1/C2/C3)**:

- **No language baselines or config surface changes.** The `produces_code` and
  language-detection features are deferred to a follow-up todo. The engine
  supports them structurally (the `produces_code` field exists in the step
  schema) but this refactor does not implement language loading or add config
  keys to `teleclaude.yml`. This resolves C2 (ungrounded config surface).
- **No consolidated `/next-workflow` command.** The engine runs behind the
  existing `next_prepare()` and `next_work()` entry points and dispatches the
  same per-step commands (`/next-build`, `/next-prepare-discovery`, etc.). The
  command surface is unchanged. This resolves C3 (ungrounded command
  architecture).
- **Single coherent delivery.** With language baselines and command surface
  removed, what remains is one indivisible behavior: the engine, its YAML
  definitions, the characterization test harness, and the internal swap. None
  of these pieces are independently shippable — the engine without YAMLs is
  useless, the YAMLs without the swap are dead files. This resolves C1
  (independently shippable workstreams bundled together).

**Approach**: TDD-compliant refactoring.
1. Capture current behavior in characterization tests (safety net).
2. Build the engine alongside the current code (RED-GREEN for engine tests).
3. Swap the engine into `next_prepare()` and `next_work()`.
4. Verify characterization tests still pass (equivalence proof).
5. Remove dead step-handler code.

---

## Phase 1: Safety Net

### Task 1.1: Characterization tests for prepare machine

**File(s):** `tests/unit/core/next_machine/test_prepare_equivalence.py`

**Why**: The prepare machine has 10 states with complex routing (review loops,
grounding checks, re-grounding, blocking). Characterization tests capture the
execution-significant dispatch contract for each reachable state so the
refactoring can be verified mechanically. Without these, behavioral drift during
the swap is invisible — the builder would have no way to confirm the engine
produces the same output as the hand-coded handlers.

- [ ] Test INPUT_ASSESSMENT → dispatches `SlashCommand.NEXT_PREPARE_DISCOVERY`
      when `requirements.md` is missing
- [ ] Test INPUT_ASSESSMENT → auto-advances to REQUIREMENTS_REVIEW when
      `requirements.md` exists (returns `keep_going=True`)
- [ ] Test TRIANGULATION → dispatches `SlashCommand.NEXT_PREPARE_DISCOVERY`
      when `requirements.md` is missing
- [ ] Test TRIANGULATION → advances to REQUIREMENTS_REVIEW when
      `requirements.md` appears, emits `prepare.requirements_drafted` event
- [ ] Test REQUIREMENTS_REVIEW → dispatches
      `SlashCommand.NEXT_REVIEW_REQUIREMENTS` when no verdict
- [ ] Test REQUIREMENTS_REVIEW → advances to PLAN_DRAFTING when verdict is
      `approve`, emits `prepare.requirements_approved` event
- [ ] Test REQUIREMENTS_REVIEW → loops to TRIANGULATION when verdict is
      `needs_work` (within round limit), includes findings in note
- [ ] Test REQUIREMENTS_REVIEW → transitions to BLOCKED when round limit
      exceeded (rounds > `DEFAULT_MAX_REVIEW_ROUNDS`)
- [ ] Test PLAN_DRAFTING → dispatches `SlashCommand.NEXT_PREPARE_DRAFT` when
      `implementation-plan.md` is missing
- [ ] Test PLAN_DRAFTING → advances to PLAN_REVIEW when plan exists, emits
      `prepare.plan_drafted` event
- [ ] Test PLAN_REVIEW → dispatches `SlashCommand.NEXT_REVIEW_PLAN` when no
      verdict
- [ ] Test PLAN_REVIEW → advances to GATE when verdict is `approve`, emits
      `prepare.plan_approved` event
- [ ] Test PLAN_REVIEW → loops to PLAN_DRAFTING when verdict is `needs_work`
      (within round limit), includes findings in note
- [ ] Test PLAN_REVIEW → transitions to BLOCKED when round limit exceeded
- [ ] Test GATE → dispatches `SlashCommand.NEXT_PREPARE_GATE` when DOR score
      below `DOR_READY_THRESHOLD` (8)
- [ ] Test GATE → advances to GROUNDING_CHECK when DOR score >= 8, calls
      `sync_main_to_worktree`
- [ ] Test GROUNDING_CHECK → transitions to PREPARED when grounding is fresh
      (first grounding or no staleness)
- [ ] Test GROUNDING_CHECK → transitions to RE_GROUNDING when input digest
      changed
- [ ] Test GROUNDING_CHECK → transitions to RE_GROUNDING when referenced paths
      changed between `base_sha` and HEAD
- [ ] Test GROUNDING_CHECK → transitions to RE_GROUNDING when git fails
      (fail-closed)
- [ ] Test RE_GROUNDING → dispatches `SlashCommand.NEXT_PREPARE_DRAFT` with
      changed-file note and resets plan review verdict
- [ ] Test PREPARED → returns `format_prepared()` output
- [ ] Test BLOCKED → returns blocked message with blocker reason
- [ ] Test `_derive_prepare_phase()` → correctly derives phase from artifact
      existence for legacy todos without `prepare_phase` in state

**Testing approach**: Each test constructs a representative `state.yaml` dict
and mocks the filesystem (artifact existence checks via `check_file_has_content`
and `check_file_exists`). Tests assert on execution-significant dispatch fields
(command, args, subfolder, `next_call`, `pre_dispatch`, event emission) — not on
human-facing orchestration prose.

**Verification**: All tests pass against the current `next_prepare()`
implementation. Run: `pytest tests/unit/core/next_machine/test_prepare_equivalence.py -v`

### Task 1.2: Characterization tests for work machine

**File(s):** `tests/unit/core/next_machine/test_work_equivalence.py`

**Why**: The work machine derives routing from `build` and `review` status
combinations in `state.yaml`, plus precondition checks (stash debt, dependencies,
preparation freshness). Each combination produces a different dispatch instruction.
Characterization tests capture the execution-significant dispatch contract to
prove equivalence after the swap. The work machine is 600+ lines of routing
logic — without tests, any subtle difference in engine output breaks
orchestrator/worker contracts silently.

- [ ] Test build=pending → dispatches `SlashCommand.NEXT_BUILD` with
      `pre_dispatch` containing mark-phase command
- [ ] Test build=started → dispatches `SlashCommand.NEXT_BUILD` (same as
      pending, resumed build)
- [ ] Test build=complete, review=pending → runs `run_build_gates()`, then
      dispatches `SlashCommand.NEXT_REVIEW_BUILD` if gates pass
- [ ] Test build=complete, review=pending, gates fail → returns build gate
      failure message with re-dispatch instruction
- [ ] Test build=complete, review=pending, `verify_artifacts()` fails →
      returns artifact verification failure
- [ ] Test review=changes_requested → dispatches
      `SlashCommand.NEXT_FIX_REVIEW` with peer conversation note
- [ ] Test review=approved, finalize.status=pending, no deferrals → dispatches
      `SlashCommand.NEXT_FINALIZE`, emits `review.approved` event
- [ ] Test review=approved, finalize.status=pending, has deferrals → dispatches
      `next-defer` before finalize
- [ ] Test review=approved, finalize.status=ready → emits integration events
      (`emit_branch_pushed`, `emit_deployment_started`) and returns handoff
      complete
- [ ] Test review=approved, finalize.status=handed_off → returns
      `FINALIZE_ALREADY_HANDED_OFF` error
- [ ] Test state repair: review=approved + build!=complete → repairs build to
      complete
- [ ] Test stale approval guard: review=approved with new commits past baseline
      → resets review=pending
- [ ] Test review round limit exceeded → returns `REVIEW_ROUND_LIMIT` error
- [ ] Test bug route: kind=bug → dispatches `SlashCommand.NEXT_BUGS_FIX`
      instead of `SlashCommand.NEXT_BUILD`
- [ ] Test precondition: stash debt → returns stash debt error before any
      routing
- [ ] Test precondition: missing requirements/plan → returns `NOT_PREPARED`
      error
- [ ] Test precondition: stale preparation (prepare_phase != prepared) →
      returns `STALE` error
- [ ] Test precondition: uncommitted changes → returns uncommitted changes
      instruction

**Testing approach**: Same as Task 1.1 — construct state dicts, mock filesystem
and git operations, assert execution-significant dispatch fields. Precondition
tests mock `get_stash_entries`, `check_file_has_content`, `read_phase_state`.

**Verification**: All tests pass against the current `next_work()` implementation.
Run: `pytest tests/unit/core/next_machine/test_work_equivalence.py -v`

---

## Phase 2: Engine Foundation

### Task 2.1: Workflow definition types and YAML loader

**File(s):** `teleclaude/core/next_machine/engine.py`

**Why**: The engine needs typed representations of workflow definitions before it
can interpret them. Defining the data model first ensures the YAML files and the
engine code agree on structure. Using dataclasses (matching the codebase pattern
in `core.py` — see `WorktreePrepDecision`, `EnsureWorktreeResult`,
`RoadmapEntry`, `DeliveredEntry`) provides type safety and IDE support. The types
also serve as the canonical documentation of the workflow schema.

- [ ] Define `ProducerConfig` dataclass: `required_reads: list[str]`,
      `artifacts: list[str]`, `inputs: list[StepInput]`, `thinking_mode: str`,
      `validator: str | None`, `command: str` (the `SlashCommand` value to
      dispatch)
- [ ] Define `StepInput` dataclass: `step: str`, `artifacts: list[str]`
- [ ] Define `ReviewerConfig` dataclass: `required_reads: list[str]`,
      `artifacts: list[str]`, `thinking_mode: str`, `command: str`
- [ ] Define `StepEvents` dataclass: `produced: str`, `approved: str | None`
- [ ] Define `StepDefinition` dataclass: `name: str`, `producer: ProducerConfig`,
      `reviewer: ReviewerConfig | None`, `max_rounds: int`, `human_gate: bool`,
      `needs_worktree: bool`, `produces_code: bool`, `state_key: str`,
      `events: StepEvents`
- [ ] Define `WorkflowDefinition` dataclass: `name: str`, `description: str`,
      `steps: list[StepDefinition]`
- [ ] Implement `load_workflow(path: Path) -> WorkflowDefinition` that parses
      YAML into typed dataclasses. Validate required fields, raise `ValueError`
      with descriptive messages for missing or invalid fields
- [ ] Cache loaded workflows at module level to avoid repeated YAML parsing

**Verification**: Write unit tests in
`tests/unit/core/next_machine/test_workflow_engine.py`:
- Valid YAML loads without error and produces correct dataclass instances
- Missing required field raises `ValueError` naming the field
- Invalid field type raises `ValueError`
- Loader is idempotent (loading same file twice returns equivalent objects)

### Task 2.2: Workflow YAML definitions

**File(s):** `workflows/prepare.yaml`, `workflows/work.yaml`

**Why**: These are the declarative transcriptions of the current prepare and work
state machine step sequences. Each step carries enough metadata for the engine to
construct the same dispatch instructions the current hand-coded handlers produce.
The YAML must match the existing step progression exactly — any deviation is a
behavioral change. These files are the engine's configuration; without them the
engine has nothing to interpret.

**`workflows/prepare.yaml`** — transcription of `_prepare_dispatch()` routing
(core.py:3433-3462) and the individual `_prepare_step_*` handlers:

- [ ] Step `input_assessment`: producer command =
      `SlashCommand.NEXT_PREPARE_DISCOVERY`, no reviewer, state_key =
      `prepare_phase`, produces `todos/{slug}/requirements.md`, events match
      `_prepare_step_input_assessment`
- [ ] Step `triangulation`: producer command =
      `SlashCommand.NEXT_PREPARE_DISCOVERY`, no reviewer, state_key =
      `prepare_phase`, events include `prepare.requirements_drafted` and
      `prepare.triangulation_started`
- [ ] Step `requirements`: reviewer command =
      `SlashCommand.NEXT_REVIEW_REQUIREMENTS`, state_key =
      `requirements_review`, max_rounds = 3, review loop routes back to
      triangulation on `needs_work`
- [ ] Step `plan`: producer command = `SlashCommand.NEXT_PREPARE_DRAFT`,
      reviewer command = `SlashCommand.NEXT_REVIEW_PLAN`, state_key =
      `plan_review`, max_rounds = 3
- [ ] Step `gate`: producer command = `SlashCommand.NEXT_PREPARE_GATE`,
      no reviewer, state_key = `dor`, DOR threshold = 8
- [ ] Step `grounding_check`: no dispatch (mechanical check), state_key =
      `grounding`
- [ ] Step `re_grounding`: producer command =
      `SlashCommand.NEXT_PREPARE_DRAFT`, resets plan review verdict
- [ ] Steps `prepared` and `blocked`: terminal states

**`workflows/work.yaml`** — transcription of `next_work()` routing logic
(core.py:3886-4200):

- [ ] Step `build`: producer command = `SlashCommand.NEXT_BUILD`, bug variant
      command = `SlashCommand.NEXT_BUGS_FIX`, pre_dispatch = mark-phase
      build:started, no reviewer
- [ ] Step `gates`: no dispatch (mechanical validation), runs
      `run_build_gates` and `verify_artifacts`
- [ ] Step `review`: producer command = `SlashCommand.NEXT_REVIEW_BUILD`,
      max_rounds from state, state_key = `review`
- [ ] Step `fix`: producer command = `SlashCommand.NEXT_FIX_REVIEW`, triggered
      by review verdict = `changes_requested`
- [ ] Step `deferrals`: producer command = `next-defer`, triggered by
      `has_pending_deferrals`
- [ ] Step `finalize`: producer command = `SlashCommand.NEXT_FINALIZE`,
      finalize handoff logic for `ready` → `handed_off` transition
- [ ] Verify both YAML files load successfully with the loader from Task 2.1

**Verification**: Run loader tests against both files. Cross-reference each
step's metadata against the corresponding handler in `core.py` to confirm field
equivalence. Each step's `command`, `state_key`, `artifacts`, `events`, and
`max_rounds` must match the current handler's behavior.

---

## Phase 3: Engine Core

### Task 3.1: Step resolution from state

**File(s):** `teleclaude/core/next_machine/engine.py`

**Why**: The engine's core job is to look at `state.yaml` and determine which
workflow step is current and what action to take (dispatch producer, dispatch
reviewer, advance to next step, or block). This mirrors what
`_derive_prepare_phase()` (core.py:2967-2996) and the `next_work()` routing
block (core.py:3886-4200) do today, but configured by step metadata instead of
hand-coded conditionals. The engine makes routing data-driven so new workflows
can be added without modifying Python.

**For prepare workflow**:
- [ ] Implement `resolve_prepare_step(workflow, state, slug, cwd)` that:
  - Reads `state.prepare_phase` to determine current phase
  - Falls back to `_derive_prepare_phase()` for legacy todos without
    `prepare_phase` (preserving backward compatibility)
  - Returns `(step, action)` where action is one of: `dispatch_producer`,
    `dispatch_reviewer`, `advance`, `block`, `terminal`
- [ ] Handle review loop: if step has reviewer and verdict is `needs_work`,
      action is `dispatch_producer` with findings (FIX MODE equivalent).
      Implements the same round-counting logic as
      `_prepare_step_requirements_review` (core.py:3079-3115) and
      `_prepare_step_plan_review` (core.py:3175-3210)
- [ ] Handle review round limit: if rounds exceed `max_rounds`, action is
      `block` — same as current BLOCKED transition
- [ ] Handle grounding check: mechanical staleness check against `base_sha`,
      `input_digest`, and `referenced_paths` — same logic as
      `_prepare_step_grounding_check` (core.py:3258-3366)

**For work workflow**:
- [ ] Implement `resolve_work_step(workflow, state, slug, worktree_cwd, cwd)`
      that:
  - Reads `build` and `review` status from state
  - Applies state repair (review=approved implies build=complete) — same as
    core.py:3896-3908
  - Applies stale approval guard (new commits past baseline) — same as
    core.py:3912-3933
  - Routes to the correct step based on status combination
  - Returns `(step, action, context)` where context carries step-specific data
    (findings, gate output, etc.)
- [ ] Handle bug variant: when `kind=bug`, dispatch `NEXT_BUGS_FIX` instead
      of `NEXT_BUILD` — same as core.py:4050-4063
- [ ] Handle gate validation: build gates and artifact verification run between
      build completion and review dispatch — same as core.py:4075-4111
- [ ] Handle finalize handoff: `ready` → emit integration events → `handed_off`
      — same as core.py:3949-4002
- [ ] Handle deferrals check: between review approval and finalize dispatch —
      same as core.py:4145-4160

**Verification**: Unit tests in `test_workflow_engine.py` for each resolution
path. Mock filesystem for artifact checks and git operations. Assert correct
`(step, action)` tuples for representative state combinations matching the
characterization test scenarios from Phase 1.

### Task 3.2: Dispatch instruction emission

**File(s):** `teleclaude/core/next_machine/engine.py`

**Why**: The engine must produce output in the exact same format as the current
dispatch infrastructure. All current handlers call `format_tool_call()` with
specific arguments. The engine must construct those same arguments from step
metadata. Reusing `format_tool_call()` directly (not reimplementing it) ensures
format compatibility — the engine only changes how the arguments are derived,
not how they are formatted.

- [ ] Implement `emit_dispatch(step, action, slug, cwd, worktree_cwd, db, ...) -> str`
      that constructs `format_tool_call()` arguments from step metadata:
  - `command` from step's producer or reviewer `command` field
  - `args` = slug
  - `project` = cwd
  - `guidance` from `compose_agent_guidance(db)` (existing function)
  - `subfolder` = `{WORKTREE_DIR}/{slug}` when step has `needs_worktree`
  - `note` from step-specific context (findings, changed files, etc.)
  - `next_call` = `telec todo prepare/work {slug}`
  - `pre_dispatch` from step-specific pre-dispatch requirements
- [ ] Preserve `POST_COMPLETION` templates: the engine passes the same
      `completion_args` to `format_tool_call()` as the current handlers — the
      `POST_COMPLETION` dict (core.py:184-271) is reused unchanged
- [ ] Emit lifecycle events at transitions using `_emit_prepare_event()` and
      the work event emission helpers (`emit_branch_pushed`,
      `emit_deployment_started`, `emit_review_approved`) — same functions,
      same call sites, same payloads
- [ ] Emit error responses using `format_error()` for precondition failures
      and terminal states — same codes and messages

**Verification**: Unit tests asserting execution-significant dispatch fields for
each step (command, args, subfolder, `next_call`, `pre_dispatch`, and required
transition-specific markers) while avoiding full-string assertions on
human-facing orchestration prose.

### Task 3.3: Named validator registry

**File(s):** `teleclaude/core/next_machine/validators.py`

**Why**: Workflow steps can request validation beyond the default
artifact-existence check. The current code has this logic inline in `next_work()`
— `run_build_gates()` (core.py:449-548) and `verify_artifacts()`
(core.py:680-876) are called directly in the routing block. A named registry
lets steps declare their validator by name in YAML, and the engine looks it up at
runtime. This decouples validation logic from step routing without duplicating the
validation code — the registry references existing functions.

- [ ] Define validator protocol: `Callable[[str, str, bool], tuple[bool, str]]`
      taking `(worktree_cwd, slug, is_bug)` and returning `(passed, output)`.
      The `is_bug` parameter preserves the current bug-variant behavior in
      `verify_artifacts()` (core.py:680, `is_bug` kwarg)
- [ ] Create registry dict mapping names to callables:
  - `"build_gates"` → `run_build_gates` (core.py:449)
  - `"artifact_verification"` → `verify_artifacts` (core.py:680)
- [ ] Implement `run_validators(step, worktree_cwd, slug, is_bug) -> (passed, output)`
      that runs the named validator if configured, chaining results. Default
      behavior (no validator field): skip validation (artifact existence is
      checked by the engine separately)
- [ ] Keep `run_build_gates()` and `verify_artifacts()` functions in `core.py`
      — the registry references them, does not duplicate them. Import paths
      use `from teleclaude.core.next_machine.core import run_build_gates, verify_artifacts`

**Verification**: Unit tests: registry lookup returns correct callable, unknown
validator name raises `KeyError` with descriptive message, validator chaining
produces combined output.

---

## Phase 4: Migration

### Task 4.1: Replace next_prepare() internals with engine

**File(s):** `teleclaude/core/next_machine/core.py`

**Why**: This is the first half of the actual refactoring. The prepare machine's
10 step handlers (`_prepare_step_input_assessment` through
`_prepare_step_blocked`, core.py:3004-3425) and the `_prepare_dispatch()` router
(core.py:3433-3462) become engine calls. The precondition checks (slug
resolution, roadmap validation, container detection — core.py:3540-3565) stay in
`next_prepare()` unchanged because they are entry-point concerns, not
workflow-step concerns. The dispatch loop structure (core.py:3567-3594) is
preserved with the engine providing the `(keep_going, instruction)` tuple.

- [ ] Load prepare workflow definition at module level (cached by loader)
- [ ] Replace the dispatch loop body in `next_prepare()`: instead of calling
      `_prepare_dispatch(phase=..., state=...)`, call the engine's
      `resolve_prepare_step()` and `emit_dispatch()` — both return the same
      `(continue_loop, instruction)` contract
- [ ] Preserve `_derive_prepare_phase()` (core.py:2967-2996) as a fallback —
      the engine calls it when `prepare_phase` is missing from state, matching
      the current behavior at core.py:3571-3575
- [ ] Preserve all event emission: engine calls `_emit_prepare_event()` at the
      same transition points with the same event types. Cross-reference: each
      `_emit_prepare_event()` call in the current handlers must have a
      corresponding emission in the engine's step resolution
- [ ] Run characterization tests from Task 1.1

**Verification**: All characterization tests from Task 1.1 pass with the engine.
`pytest tests/unit/core/next_machine/test_prepare_equivalence.py -v` — zero
failures. Additionally, the engine's dispatch for each state must call
`format_tool_call()` with the same execution-significant arguments as the handler
it replaces.

### Task 4.2: Replace next_work() internals with engine

**File(s):** `teleclaude/core/next_machine/core.py`

**Why**: This is the second half of the refactoring. The work machine's routing
block (core.py:3886-4200 — the long if/elif chain based on `build_status` and
`review_status`) becomes engine step resolution and dispatch. The precondition
checks (slug resolution, dependency gating, stash debt, worktree management,
uncommitted changes — core.py:3613-3878) stay in `next_work()` unchanged. They
run before any workflow step and are entry-point concerns.

- [ ] Load work workflow definition at module level (cached by loader)
- [ ] Replace the routing block (from comment "7. Route from worktree-owned
      build/review state" at core.py:3886 through the end of `next_work()`)
      with engine calls: `resolve_work_step()` for routing and `emit_dispatch()`
      for output
- [ ] Preserve all precondition checks unchanged:
  - Canonical CWD normalization (core.py:3613-3618)
  - Group sweep (core.py:3621)
  - Slug resolution and dependency gating (core.py:3626-3731)
  - Stash debt check (core.py:3738-3742)
  - Artifact existence validation (core.py:3744-3778)
  - Preparation freshness gate (core.py:3781-3801)
  - Worktree ensure/sync (core.py:3803-3870)
  - Uncommitted changes check (core.py:3874-3877)
  - Item claiming (core.py:3882-3884)
- [ ] Preserve state repair logic: review=approved + build!=complete →
      build=complete (core.py:3896-3908). This runs inside the engine's
      `resolve_work_step()` as a pre-routing correction
- [ ] Preserve stale approval guard (core.py:3912-3933) — also inside
      `resolve_work_step()`
- [ ] Preserve finalize handoff logic (core.py:3949-4002) — the engine handles
      the ready → integration event emission → handed_off transition
- [ ] Preserve bug route (core.py:4050-4063) — engine detects `kind=bug` from
      state and uses the bug step variant command
- [ ] Run characterization tests from Task 1.2

**Verification**: All characterization tests from Task 1.2 pass with the engine.
`pytest tests/unit/core/next_machine/test_work_equivalence.py -v` — zero
failures.

---

## Phase 5: Cleanup and Verification

### Task 5.1: Remove dead code

**File(s):** `teleclaude/core/next_machine/core.py`,
`teleclaude/core/next_machine/__init__.py`

**Why**: After the engine replaces the step handlers, the old handler functions
are dead code. Removing them reduces `core.py` by ~430 lines (handlers +
dispatcher) and prevents confusion about which code path is active. Dead code
also creates false dependencies and makes refactoring harder.

- [ ] Remove `_prepare_step_input_assessment()` (core.py:3004)
- [ ] Remove `_prepare_step_triangulation()` (core.py:3033)
- [ ] Remove `_prepare_step_requirements_review()` (core.py:3063)
- [ ] Remove `_prepare_step_plan_drafting()` (core.py:3130)
- [ ] Remove `_prepare_step_plan_review()` (core.py:3159)
- [ ] Remove `_prepare_step_gate()` (core.py:3225)
- [ ] Remove `_prepare_step_grounding_check()` (core.py:3258)
- [ ] Remove `_prepare_step_re_grounding()` (core.py:3369)
- [ ] Remove `_prepare_step_prepared()` (core.py:3408)
- [ ] Remove `_prepare_step_blocked()` (core.py:3413)
- [ ] Remove `_prepare_dispatch()` (core.py:3433) — the old step router
- [ ] Remove inline routing code from `next_work()` (core.py:3886-4200) that
      was replaced by engine calls
- [ ] Keep all shared infrastructure intact: `format_tool_call()`,
      `format_error()`, `format_prepared()`, `format_uncommitted_changes()`,
      `format_stash_debt()`, `format_build_gate_failure()`,
      `format_finalize_handoff_complete()`, `run_build_gates()`,
      `verify_artifacts()`, `_emit_prepare_event()`, `_derive_prepare_phase()`,
      all roadmap/icebox/delivered management, all worktree management, all
      state read/write, all git helpers — these are shared infrastructure, not
      machine-specific handlers
- [ ] Update `__init__.py` exports if any removed functions were previously
      exported (currently only `_prepare_worktree` is explicitly re-exported)

**Verification**: `make lint` passes (no unused imports or functions flagged).
`make test` passes (full suite, not just characterization tests).

### Task 5.2: Final verification

- [ ] Run full test suite: `make test`
- [ ] Run linting and type checking: `make lint`
- [ ] Verify all characterization tests pass (behavioral equivalence proven)
- [ ] Verify engine unit tests pass
- [ ] Verify `telec todo prepare <slug>` works against a representative todo
- [ ] Verify `telec todo work <slug>` works against a representative todo
- [ ] Verify no regressions in existing prepare/work flows
- [ ] Confirm state.yaml format unchanged — existing in-progress todos
      continue without migration
- [ ] Verify `POST_COMPLETION` templates are unchanged — same instructions
      emitted for each command
- [ ] Verify `SlashCommand` enum is unchanged — no new entries needed

---

## Referenced Files

### Modified
- `teleclaude/core/next_machine/core.py` — Replace step handlers with engine
  calls, remove dead handler code (~430 lines removed)

### Created
- `teleclaude/core/next_machine/engine.py` — Workflow engine: types, loader,
  step resolution, dispatch emission
- `teleclaude/core/next_machine/validators.py` — Named validator registry
  referencing existing validation functions
- `workflows/prepare.yaml` — Prepare workflow definition
- `workflows/work.yaml` — Work workflow definition
- `tests/unit/core/next_machine/test_prepare_equivalence.py` — Prepare
  characterization tests
- `tests/unit/core/next_machine/test_work_equivalence.py` — Work
  characterization tests
- `tests/unit/core/next_machine/test_workflow_engine.py` — Engine unit tests

### Unchanged (used by engine, not modified)
- `teleclaude/core/next_machine/__init__.py` — Thin wrapper, may need export
  update only if removed functions were public
- `teleclaude/core/next_machine/prepare.py` — Thin wrapper, re-exports
  `next_prepare`
- `teleclaude/core/next_machine/work.py` — Thin wrapper, re-exports `next_work`
- `teleclaude/core/integration_bridge.py` — Event emission (called by engine)
- `teleclaude/core/agents.py` — Agent guidance (called by engine)
- `teleclaude/core/db.py` — Database access (passed to engine)
- `teleclaude/constants.py` — `SlashCommand` enum (unchanged, no new entries)

## Deferred to Follow-up Todos

These items were in the original input but removed from this refactor's scope
based on plan review findings:

- **Language baselines and config surface**: `languages/python/baseline.md`,
  `languages/typescript/baseline.md`, `teleclaude.yml` `language`/`languages`
  keys, engine language detection. The engine schema supports `produces_code`
  but this refactor does not implement the language loading behavior.
- **Consolidated `/next-workflow` command**: `agents/commands/next-workflow.md`,
  `SlashCommand.NEXT_WORKFLOW` enum entry. Requires architectural changes to
  the command/session-role plumbing that are not in scope for this refactor.
