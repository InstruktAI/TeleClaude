# Implementation Plan: workflow-engine-refactor

## Overview

Replace the bespoke prepare and work state machines in
`teleclaude/core/next_machine/core.py` with a configurable workflow engine that
interprets YAML workflow definitions. The engine reads `state.yaml`, resolves the
current step, and emits the same fully-specified dispatch instructions the current
hand-coded handlers produce. Pure refactoring — behavioral equivalence is the
acceptance criterion.

**Approach**: TDD-compliant refactoring.
1. Capture current behavior in characterization tests (safety net).
2. Build the engine alongside the current code (RED-GREEN for engine tests).
3. Swap the engine into `next_prepare()` and `next_work()`.
4. Verify characterization tests still pass (equivalence proof).
5. Remove dead step-handler code.

This approach is appropriate because the input specifies the exact YAML schema,
engine mechanics, and migration strategy — the builder executes a well-defined
transformation, not an open-ended design.

---

## Phase 1: Safety Net

### Task 1.1: Characterization tests for prepare machine

**File(s):** `tests/unit/core/next_machine/test_prepare_equivalence.py`

**Why**: The prepare machine has 10 states with complex routing (review loops,
grounding checks, re-grounding, blocking). Characterization tests capture the
execution-significant dispatch contract for each reachable state so the
refactoring can be verified mechanically without locking human-facing prose.
Without these, behavioral drift is invisible.

- [ ] Test INPUT_ASSESSMENT → dispatches `/next-prepare-discovery` when
      `requirements.md` is missing
- [ ] Test INPUT_ASSESSMENT → auto-advances to REQUIREMENTS_REVIEW when
      `requirements.md` exists
- [ ] Test TRIANGULATION → dispatches `/next-prepare-discovery` when
      `requirements.md` is missing
- [ ] Test TRIANGULATION → advances to REQUIREMENTS_REVIEW when
      `requirements.md` appears
- [ ] Test REQUIREMENTS_REVIEW → dispatches `/next-review-requirements` when
      no verdict
- [ ] Test REQUIREMENTS_REVIEW → advances to PLAN_DRAFTING when verdict is
      `approve`
- [ ] Test REQUIREMENTS_REVIEW → loops to TRIANGULATION when verdict is
      `needs_work` (within round limit)
- [ ] Test REQUIREMENTS_REVIEW → transitions to BLOCKED when round limit
      exceeded
- [ ] Test PLAN_DRAFTING → dispatches `/next-prepare-draft` when
      `implementation-plan.md` is missing
- [ ] Test PLAN_DRAFTING → advances to PLAN_REVIEW when plan exists
- [ ] Test PLAN_REVIEW → dispatches `/next-review-plan` when no verdict
- [ ] Test PLAN_REVIEW → advances to GATE when verdict is `approve`
- [ ] Test PLAN_REVIEW → loops to PLAN_DRAFTING when verdict is `needs_work`
      (within round limit)
- [ ] Test PLAN_REVIEW → transitions to BLOCKED when round limit exceeded
- [ ] Test GATE → dispatches `/next-prepare-gate` when DOR score below
      threshold
- [ ] Test GATE → advances to GROUNDING_CHECK when DOR score >= 8
- [ ] Test GROUNDING_CHECK → transitions to PREPARED when grounding is fresh
- [ ] Test GROUNDING_CHECK → transitions to RE_GROUNDING when grounding is
      stale (input digest changed or referenced files changed)
- [ ] Test RE_GROUNDING → dispatches `/next-prepare-draft` with changed-file
      note and resets plan review verdict
- [ ] Test PREPARED → returns `format_prepared()` output
- [ ] Test BLOCKED → returns blocked message with blocker reason

**Verification**: All tests pass against the current `next_prepare()` implementation.
Run: `pytest tests/unit/core/next_machine/test_prepare_equivalence.py -v`

### Task 1.2: Characterization tests for work machine

**File(s):** `tests/unit/core/next_machine/test_work_equivalence.py`

**Why**: The work machine derives routing from `build` and `review` status
combinations in `state.yaml`. Each combination produces a different dispatch
instruction. Characterization tests capture the execution-significant dispatch
contract and state transitions to prove equivalence after the refactoring.

- [ ] Test build=pending → dispatches `/next-build` with pre_dispatch marking
      `build=started`
- [ ] Test build=started → dispatches `/next-build` (same as pending)
- [ ] Test build=complete, review=pending → runs build gates, then dispatches
      `/next-review-build` if gates pass
- [ ] Test build=complete, review=pending, gates fail → returns build gate
      failure with re-dispatch instruction
- [ ] Test build=complete, review=pending, artifact verification fails →
      returns artifact failure
- [ ] Test review=changes_requested → dispatches `/next-fix-review`
- [ ] Test review=approved, finalize.status=pending, no deferrals → dispatches
      `/next-finalize`
- [ ] Test review=approved, finalize.status=pending, has deferrals → dispatches
      `/next-defer`
- [ ] Test review=approved, finalize.status=ready → emits integration events
      and returns handoff complete
- [ ] Test review=approved, finalize.status=handed_off → returns
      FINALIZE_ALREADY_HANDED_OFF error
- [ ] Test state repair: review=approved + build!=complete → repairs to
      build=complete
- [ ] Test stale approval guard: review=approved with new commits past baseline
      → resets review=pending
- [ ] Test review round limit exceeded → returns REVIEW_ROUND_LIMIT error
- [ ] Test bug route: kind=bug → dispatches `/next-bugs-fix` instead of
      `/next-build`
- [ ] Test precondition: stash debt → returns STASH_DEBT error
- [ ] Test precondition: missing requirements/plan → returns NOT_PREPARED error
- [ ] Test precondition: stale preparation → returns STALE error
- [ ] Test precondition: uncommitted changes → returns UNCOMMITTED_CHANGES
      instruction

**Verification**: All tests pass against the current `next_work()` implementation.
Run: `pytest tests/unit/core/next_machine/test_work_equivalence.py -v`

---

## Phase 2: Engine Foundation

### Task 2.1: Workflow definition types and YAML loader

**File(s):** `teleclaude/core/next_machine/engine.py`

**Why**: The engine needs typed representations of workflow definitions before it
can interpret them. Defining the data model first ensures the YAML files and the
engine code agree on structure. The types also serve as documentation of the
workflow schema.

- [ ] Define `ProducerConfig` dataclass: `required_reads`, `artifacts`,
      `inputs`, `thinking_mode`, `validator`
- [ ] Define `ReviewerConfig` dataclass: `required_reads`, `artifacts`,
      `thinking_mode`
- [ ] Define `StepDefinition` dataclass: `name`, `producer`, `reviewer`
      (optional), `max_rounds`, `human_gate`, `needs_worktree`,
      `produces_code`, `state_key`, `events`
- [ ] Define `WorkflowDefinition` dataclass: `name`, `description`, `steps`
- [ ] Implement `load_workflow(path: Path) -> WorkflowDefinition` that parses
      YAML into typed dataclasses with validation
- [ ] Implement `load_all_workflows(base_dir: Path) -> dict[str, WorkflowDefinition]`
      for loading all YAML files from the workflows directory

**Verification**: Write unit tests for the loader: valid YAML loads without error,
invalid YAML raises descriptive errors, missing fields produce clear failures.

### Task 2.2: Workflow YAML definitions

**File(s):** `workflows/prepare.yaml`, `workflows/work.yaml`

**Why**: These are the declarative transcriptions of the current prepare and work
state machine step sequences. Each step carries enough metadata for the engine to
construct the same dispatch instructions the current hand-coded handlers produce.
The YAML must match the existing step progression exactly — any deviation is a
behavioral change.

- [ ] Write `workflows/prepare.yaml` with steps: requirements, plan, gate
      (matching current PreparePhase progression: INPUT_ASSESSMENT/TRIANGULATION →
      REQUIREMENTS_REVIEW → PLAN_DRAFTING → PLAN_REVIEW → GATE →
      GROUNDING_CHECK). Each step includes producer/reviewer configs with
      required_reads, artifacts, thinking_mode, state_key, and events matching
      current `_prepare_step_*` handlers
- [ ] Write `workflows/work.yaml` with steps: build, review, fix, finalize
      (matching current `next_work()` routing: build → gates → review →
      fix-loop → deferrals → finalize → handoff). Each step includes
      dispatch command, required artifacts, thinking_mode, and events matching
      current POST_COMPLETION templates
- [ ] Verify both YAML files load successfully with the loader from Task 2.1

**Verification**: Run loader tests against both files. Cross-reference each step's
metadata against the corresponding handler in `core.py` to confirm equivalence.

### Task 2.3: Language baseline files

**File(s):** `languages/python/baseline.md`, `languages/typescript/baseline.md`

**Why**: Code-producing workflow steps need language-specific context (test
framework conventions, RED marker syntax, spec file patterns, lint/typecheck
commands). Currently this knowledge is implicit in worker procedures. Making it
explicit and loadable means the engine can augment dispatch instructions with the
correct language conventions based on the project's `teleclaude.yml` config.

- [ ] Create `languages/python/baseline.md` with: pytest conventions,
      `pytest.mark.xfail(strict=True)` for RED markers, `tests/` spec patterns,
      `make test` / `make lint` commands
- [ ] Create `languages/typescript/baseline.md` with: vitest conventions,
      `test.fails()` for RED markers, `*.spec.ts` patterns, equivalent commands
- [ ] Add language detection helper in engine.py that reads `teleclaude.yml`
      for `language` or `languages` key

**Verification**: Loader reads baseline files without error. Language detection
returns correct language for this project (Python).

---

## Phase 3: Engine Core

### Task 3.1: Step resolution from state

**File(s):** `teleclaude/core/next_machine/engine.py`

**Why**: The engine's core job is to look at `state.yaml` and determine which
workflow step is current and what action to take (dispatch producer, dispatch
reviewer, advance to next step, or block). This mirrors what `_derive_prepare_phase()`
and the `next_work()` routing block do today, but configured by step metadata
instead of hand-coded conditionals.

- [ ] Implement `resolve_current_step(workflow, state) -> (step, action)` that:
  - Reads the `state_key` for each step in order
  - Checks artifact existence (producer.artifacts) and review verdicts
  - Returns the first step that needs work, plus the action (produce, review,
    advance, block)
- [ ] Handle review loop: if reviewer exists and verdict is `needs_work`,
      action is "re-produce with findings" (FIX MODE equivalent)
- [ ] Handle review round limit: if rounds exceed `max_rounds`, action is
      "block"
- [ ] Handle human gate: if step has `human_gate: true` and verdict is
      `approve`, pause for human confirmation before advancing
- [ ] Handle `produces_code: true`: detect project language and merge language
      baseline required_reads into producer config
- [ ] Handle `needs_worktree: true`: flag for the caller to ensure worktree
      exists before dispatch

**Verification**: Unit tests for each resolution path. Mock filesystem for artifact
checks. Assert correct (step, action) tuples for representative state combinations.

### Task 3.2: Dispatch instruction emission

**File(s):** `teleclaude/core/next_machine/engine.py`

**Why**: The engine must produce output in the exact same format as the current
`format_tool_call()` infrastructure. The dispatch instruction includes command,
args, project, guidance, subfolder, note, next_call, and post-completion
instructions. Reusing `format_tool_call()` directly ensures format compatibility.

- [ ] Implement `emit_dispatch(step, action, slug, cwd, guidance, ...) -> str`
      that constructs a `format_tool_call()` invocation from step metadata:
  - `command` from step's producer or reviewer config
  - `args` = slug
  - `project` = cwd
  - `guidance` from `compose_agent_guidance()`
  - `subfolder` from step's `needs_worktree` flag
  - `note` from step-specific context (findings, changed files, etc.)
  - `next_call` = `telec todo prepare/work {slug}`
  - `pre_dispatch` from step-specific pre-dispatch requirements
- [ ] Map step names to SlashCommand values: each step's producer/reviewer
      has a `command` field that maps to the existing SlashCommand enum
- [ ] Preserve POST_COMPLETION templates: the engine emits the same
      post-completion instructions per command as the current POST_COMPLETION dict
- [ ] Emit lifecycle events at transitions using `_emit_prepare_event()` and
      equivalent work event emission

**Verification**: Unit tests asserting execution-significant dispatch fields
for each step (command, args, subfolder, `next_call`, `pre_dispatch`, and
required transition-specific markers) while avoiding full-string assertions on
human-facing orchestration prose.

### Task 3.3: Named validator registry

**File(s):** `teleclaude/core/next_machine/validators.py`

**Why**: Workflow steps can request validation beyond the default artifact-existence
check. The current code has this logic inline (e.g., `run_build_gates()`,
`verify_artifacts()`). A named registry lets steps declare their validator by name
in YAML, and the engine looks it up at runtime. This decouples validation logic
from step routing.

- [ ] Define validator protocol: `Callable[[str, str], tuple[bool, str]]`
      taking `(worktree_cwd, slug)` and returning `(passed, output)`
- [ ] Create registry dict mapping names to callables:
  - `build_gates` → existing `run_build_gates()`
  - `artifact_verification` → existing `verify_artifacts()` (build phase)
  - `demo_validate` → existing `telec todo demo validate` invocation
- [ ] Implement `validate_step(step, worktree_cwd, slug) -> (passed, output)`
      that runs default artifact check + named validator if configured
- [ ] Keep existing `run_build_gates()` and `verify_artifacts()` functions
      in `core.py` — the registry references them, does not duplicate them

**Verification**: Unit tests: registry lookup returns correct callable, unknown
validator name raises descriptive error, default validation checks file existence.

---

## Phase 4: Migration

### Task 4.1: Replace next_prepare() internals with engine

**File(s):** `teleclaude/core/next_machine/core.py`

**Why**: This is the first half of the actual refactoring. The prepare machine's
step handlers (`_prepare_step_input_assessment` through `_prepare_step_blocked`)
and the `_prepare_dispatch()` router become a single `engine.walk(workflow, state)`
call. The precondition checks (slug resolution, roadmap validation, container
detection) stay in `next_prepare()` — they are entry-point concerns, not
workflow-step concerns.

- [ ] Load prepare workflow definition at module level or on first call
      (cached)
- [ ] Replace the dispatch loop body in `next_prepare()`: instead of calling
      `_prepare_dispatch(phase=..., state=...)`, call the engine to resolve
      the current step and emit the dispatch instruction
- [ ] Preserve the loop structure: the engine returns `(continue_loop, instruction)`
      matching the existing `_prepare_dispatch()` contract
- [ ] Preserve `_derive_prepare_phase()` as a fallback for legacy todos with
      no `prepare_phase` in state.yaml — the engine uses it to bootstrap state
- [ ] Preserve all event emission: the engine calls `_emit_prepare_event()` at
      the same transition points with the same event types
- [ ] Remove the individual `_prepare_step_*` handler functions after
      confirming characterization tests pass
- [ ] Run characterization tests from Task 1.1

**Verification**: All characterization tests from Task 1.1 pass with the engine.
`pytest tests/unit/core/next_machine/test_prepare_equivalence.py -v` — zero
failures.

### Task 4.2: Replace next_work() internals with engine

**File(s):** `teleclaude/core/next_machine/core.py`

**Why**: This is the second half of the refactoring. The work machine's routing
block (the long if/elif chain based on `build_status` and `review_status`) becomes
an engine walk through `work.yaml`. The precondition checks (slug resolution,
dependency gating, stash debt, worktree management, uncommitted changes) stay in
`next_work()` — they run before any workflow step.

- [ ] Load work workflow definition at module level or on first call (cached)
- [ ] Replace the routing block (from "7. Route from worktree-owned
      build/review state" through the end of `next_work()`) with engine step
      resolution and dispatch
- [ ] Preserve all precondition checks unchanged: slug resolution, dependency
      gating, stash debt check, artifact existence, preparation freshness,
      worktree ensure/sync, uncommitted changes, item claiming
- [ ] Preserve state repair logic: review=approved + build!=complete →
      build=complete; stale approval baseline → review=pending. These are
      pre-routing corrections that the engine consumes as clean state
- [ ] Preserve build gate and artifact verification invocation: the engine
      triggers these through the named validator registry before dispatching
      review
- [ ] Preserve finalize handoff logic: the engine handles the
      ready → integration event emission → handed_off transition
- [ ] Preserve bug route: engine detects `kind=bug` and uses the bug step
      variant (different command, different artifact checks)
- [ ] Remove the inline routing code after confirming characterization tests
      pass
- [ ] Run characterization tests from Task 1.2

**Verification**: All characterization tests from Task 1.2 pass with the engine.
`pytest tests/unit/core/next_machine/test_work_equivalence.py -v` — zero failures.

---

## Phase 5: Command Surface and Compatibility

### Task 5.1: Consolidated workflow command

**File(s):** `agents/commands/next-workflow.md` (new command artifact),
`teleclaude/constants.py`

**Why**: The requirements specify a consolidated dispatch surface where
`/next-workflow prepare discovery` resolves to the same dispatch as the current
`/next-prepare-discovery`. This gives the engine a direct entry point while the
old per-step commands remain available during transition. The engine resolves the
positional arguments to step config.

- [ ] Create command artifact `agents/commands/next-workflow.md` that accepts
      `<workflow> [step]` positional arguments
- [ ] When called with workflow only (e.g., `/next-workflow prepare`): run in
      orchestrator mode — equivalent to `telec todo prepare`
- [ ] When called with workflow + step (e.g., `/next-workflow work build`):
      run in worker mode — engine resolves the step config and loads the
      required reads for direct execution
- [ ] Add `NEXT_WORKFLOW` to the `SlashCommand` enum in `constants.py`
- [ ] Old command names (`/next-build`, `/next-prepare-discovery`, etc.)
      continue to work — no aliases needed since they are independent command
      artifacts

**Verification**: `telec sync` succeeds with the new command artifact. The command
resolves workflow + step combinations to the correct dispatch behavior.

---

## Phase 6: Cleanup and Verification

### Task 6.1: Remove dead code

**File(s):** `teleclaude/core/next_machine/core.py`,
`teleclaude/core/next_machine/__init__.py`

**Why**: After the engine replaces the step handlers, the old handler functions are
dead code. Removing them reduces maintenance burden and prevents confusion about
which code path is active.

- [ ] Remove `_prepare_step_input_assessment()` through
      `_prepare_step_blocked()` (10 functions)
- [ ] Remove `_prepare_dispatch()` (the old step router)
- [ ] Remove inline routing code from `next_work()` that was replaced by
      engine calls
- [ ] Keep all utility functions intact: `format_tool_call()`,
      `run_build_gates()`, `verify_artifacts()`, roadmap management, worktree
      management, state read/write — these are shared infrastructure, not
      machine-specific handlers
- [ ] Update `__init__.py` exports if any removed functions were public

**Verification**: `make lint` passes (no unused imports or functions flagged).
`make test` passes (full suite, not just characterization tests).

### Task 6.2: Final verification

- [ ] Run full test suite: `make test`
- [ ] Run linting and type checking: `make lint`
- [ ] Verify all characterization tests pass (behavioral equivalence proven)
- [ ] Verify engine unit tests pass
- [ ] Verify `telec todo prepare <slug>` works against a representative todo
- [ ] Verify `telec todo work <slug>` works against a representative todo
- [ ] Verify no regressions in existing prepare/work flows
- [ ] Confirm state.yaml format unchanged — existing in-progress todos
      continue without migration

---

## Referenced Files

### Modified
- `teleclaude/core/next_machine/core.py` — Replace step handlers with engine
- `teleclaude/core/next_machine/__init__.py` — Update exports
- `teleclaude/constants.py` — Add NEXT_WORKFLOW to SlashCommand

### Created
- `teleclaude/core/next_machine/engine.py` — Workflow engine
- `teleclaude/core/next_machine/validators.py` — Named validator registry
- `workflows/prepare.yaml` — Prepare workflow definition
- `workflows/work.yaml` — Work workflow definition
- `languages/python/baseline.md` — Python language baseline
- `languages/typescript/baseline.md` — TypeScript language baseline
- `tests/unit/core/next_machine/test_prepare_equivalence.py` — Prepare characterization tests
- `tests/unit/core/next_machine/test_work_equivalence.py` — Work characterization tests
- `tests/unit/core/next_machine/test_workflow_engine.py` — Engine unit tests
- `agents/commands/next-workflow.md` — Consolidated command artifact

### Unchanged (used by engine, not modified)
- `teleclaude/core/next_machine/prepare.py` — Thin wrapper, still re-exports
- `teleclaude/core/next_machine/work.py` — Thin wrapper, still re-exports
- `teleclaude/core/integration_bridge.py` — Event emission (called by engine)
- `teleclaude/core/agents.py` — Agent guidance (called by engine)
- `teleclaude/core/db.py` — Database access (passed to engine)
