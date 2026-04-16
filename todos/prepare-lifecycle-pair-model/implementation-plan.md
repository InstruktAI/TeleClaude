# prepare-lifecycle-pair-model — Implementation Plan

## Delivery Shape

- No split. [inferred] The model change is cohesive and mechanically broad, but it is still one behavior.
- Builder target: make the pair-model prep specs green, then update the existing characterization suites and docs so the machine, readiness surfaces, operator guidance, and stale-grounding recovery path agree.

## Assumptions To Build Unless Corrected

- `PreparePhase` becomes exactly `input_assessment`, `pair_discovery`, `requirements_produced`, `pair_completion`, `grounding_check`, `re_grounding`, `prepared`, `blocked`.
- `pair_completion` is the pair-owned completion boundary; `grounding_check` and `re_grounding` are mechanical phases owned by the state machine and must not dispatch more intelligent prepare workers as the primary path.
- [inferred] The pair session identity remains discoverable after `pair_completion` long enough for `re_grounding` to reuse it; if not, degraded fallback dispatch remains necessary.
- [inferred] A deferred DOR gate remains durable follow-up work and does not count as completion for the parent todo.

## Task 1. Replace the prepare phase and DOR primitives

Rationale:
The phase enum and todo-state models are the source contract for every other consumer. If they stay score-based or phase-heavy, every downstream surface will keep reintroducing the old lifecycle.

Files:

- `teleclaude/core/next_machine/_types.py`
- `teleclaude/types/todos.py`
- `teleclaude/core/next_machine/state_io.py`
- `teleclaude/api/todo_routes.py`

Makes GREEN:

- `test_prepare_phase_enum_matches_pair_model_contract`
- `test_dor_state_uses_binary_gates_and_has_no_numeric_score_fields`

Verification:

- Run `pytest tests/unit/core/next_machine/test_prepare_lifecycle_pair_model_specs.py -q`
- Re-run the affected characterization suites for state and stamp behavior:
  `pytest tests/unit/core/next_machine/test_prepare_steps.py tests/unit/core/next_machine/test_phase_derivation.py tests/unit/cli/telec/handlers/test_todo_artifacts.py -q`

## Task 2. Rebuild prepare routing around state authority, the pair checkpoint, and live-pair re-grounding

Rationale:
The core behavior change is routing. The machine must stop re-deriving prepare from artifact/review primitives, stop dispatching the old cold workers, add a real wait state after requirements, treat post-pair grounding as mechanical state-machine work, and on stale grounding relay changed-file context back to the live pair instead of defaulting to a cold draft worker.

Files:

- `teleclaude/core/next_machine/prepare.py`
- `teleclaude/core/next_machine/prepare_steps.py`
- `teleclaude/core/next_machine/prepare_scripts.py`
- `teleclaude/core/next_machine/phase_derivation.py`
- `teleclaude/core/next_machine/prepare_events.py`

Routing rewrite requirements:

- `_handle_stale_grounding` must stop using `next-prepare-draft` as the primary stale-grounding path.
- `_handle_stale_grounding` must find the live pair session for the slug and relay changed-file context to it via `telec sessions send` so the existing pair updates `implementation-plan` with full discovery context intact.
- `re_grounding` must remain a state-machine-owned mechanical phase even when it re-engages the live pair for the plan refresh.
- If no live pair session is available, `_handle_stale_grounding` may fall back to dispatching a fresh worker as a degraded recovery path.

Makes GREEN:

- `test_requirements_produced_phase_waits_for_human_continue`
- `test_next_prepare_routes_from_current_pair_phase_without_phase_derivation`
- `test_pair_completion_is_pair_boundary_and_grounding_becomes_mechanical`
- `test_re_grounding_messages_live_pair_before_cold_fallback`

Verification:

- Run `pytest tests/unit/core/next_machine/test_prepare_lifecycle_pair_model_specs.py -q`
- Re-run the routing characterization suites:
  `pytest tests/unit/core/next_machine/test_prepare_steps.py tests/unit/core/next_machine/test_state_machine_versioning_specs.py tests/unit/core/next_machine/test_phase_derivation.py -q`

## Task 3. Move work-entry and validation consumers to binary readiness

Rationale:
The pair-model change is incomplete if the work machine and repo validators still gate on `dor.score >= 8`.

Files:

- `teleclaude/core/next_machine/work_steps.py`
- `teleclaude/resource_validation/__init__.py`
- `teleclaude/core/roadmap.py`
- `teleclaude/core/todos_db/_show.py`

Makes GREEN:

- `test_work_step_build_started_accepts_binary_dor_completion_without_score`
- `test_validate_todo_ready_contract_uses_binary_dor_complete`

Verification:

- Run `pytest tests/unit/core/next_machine/test_prepare_lifecycle_pair_model_specs.py -q`
- Run the nearest existing readiness suites:
  `pytest tests/unit/core/next_machine/test_phase_derivation.py tests/unit/core/next_machine/test_state_machine_versioning_specs.py -q`

## Task 4. Align operator surfaces with the new readiness contract

Rationale:
If the CLI and TUI still expose score-based readiness or the old phase names, the implementation will be functionally correct but operationally misleading.

Files:

- `teleclaude/cli/telec/handlers/todo.py`
- `teleclaude/cli/telec/surface.py`
- `teleclaude/cli/tui/widgets/todo_row.py`
- `teleclaude/cli/tui/views/preparation_actions.py`

Makes GREEN:

- `test_todo_stamp_surface_and_handler_drop_dor_score`
- `test_prepare_phase_label_supports_pair_and_mechanical_states`

Verification:

- Run `pytest tests/unit/core/next_machine/test_prepare_lifecycle_pair_model_specs.py -q`
- Re-run nearby surface suites:
  `pytest tests/unit/cli/telec/handlers/test_todo_artifacts.py tests/unit/cli/tui/widgets/test_todo_row.py -q`

## Task 5. Rewrite the prepare command/docs set around the pair workflow

Rationale:
This experiment only becomes repeatable if the command guidance and lifecycle docs describe the same pair-owned workflow the code implements, including the fact that grounding freshness after `pair_completion` is mechanical rather than pair-owned, including the mandatory breath protocol that prevents premature convergence in paired discovery, and including the stale-grounding rule that re-engages the live pair before any degraded fallback.

Files:

- `agents/commands/next-prepare-discovery.md`
- `agents/commands/next-prepare-gate.md`
- `docs/global/software-development/procedure/lifecycle/prepare/overview.md`
- `docs/global/software-development/procedure/lifecycle/prepare/discovery.md`
- `docs/global/software-development/procedure/lifecycle/prepare/plan-draft.md`
- `docs/global/software-development/procedure/lifecycle/prepare/readiness-gate.md`
- `docs/global/software-development/procedure/lifecycle/prepare.md`
- `docs/project/design/architecture/prepare-state-machine.md`
- `docs/project/design/architecture/lifecycle-state-machines.md`
- `docs/project/spec/jobs/next-prepare.md`
- `docs/project/spec/jobs/next-prepare-discovery.md`
- `docs/project/spec/jobs/next-prepare-draft.md`
- `docs/project/spec/jobs/next-prepare-gate.md`
- `docs/project/spec/event-vocabulary.md` if event names/descriptions change

Command rewrite requirements:

- `agents/commands/next-prepare-discovery.md` must explicitly instruct agents to complete at least three full breath cycles before beginning any artifact writing.
- The command must present three cycles as a minimum floor, never as the target or focal goal.
- The command must define the cycle as `Inhale -> Hold -> Exhale` and preserve the behavioral constraints for each stage: expansion without convergence, tension without resolution, and distillation that opens the next layer.
- The command must state that premature convergence is the pair's primary failure mode and that the three-cycle floor is the non-optional guard against it.
- The command must explicitly instruct the pair to continue cycling beyond three whenever the work is not yet genuinely converged.
- The command and related prepare docs must explicitly require that no material unresolved questions, contradictions, or open lines of inquiry remain before the pair begins writing an artifact.
- The command and related prepare docs must state that the breath protocol applies across requirements, test specs, and implementation plan work, and that the cycle count may continue across artifacts when context remains continuous.
- The command and related prepare docs must describe `re_grounding` as a mechanical phase that re-engages the live pair for plan refresh before any degraded cold-worker fallback.

Makes GREEN:

- The prep specs remain the primary contract; this task keeps the docs from drifting once the code is green.

Verification:

- Run `telec docs index | rg 'prepare-state-machine|next-prepare|lifecycle-state-machines|event-vocabulary'`
- Spot-check the updated docs against the new phase set, the binary checklist contract, the explicit discovery-command instructions that three cycles is only the floor and that writing starts only once no material unresolved questions remain, and the `re_grounding` description that prioritizes the live-pair relay path.

## Task 6. Finish by turning the spec file into the permanent regression guard

Rationale:
The xfail file is the build contract. The builder must remove the xfail marker, keep every assertion intact, and then update adjacent legacy suites only where the intentional behavior changed.

Files:

- `tests/unit/core/next_machine/test_prepare_lifecycle_pair_model_specs.py`
- Existing nearby suites touched by the new contract:
  `tests/unit/core/next_machine/test_prepare_steps.py`
  `tests/unit/core/next_machine/test_phase_derivation.py`
  `tests/unit/core/next_machine/test_state_machine_versioning_specs.py`
  `tests/unit/cli/telec/handlers/test_todo_artifacts.py`
  `tests/unit/cli/tui/widgets/test_todo_row.py`

Verification:

- Start with the spec file only.
- Expand only to the directly affected existing suites listed above.
- Let pre-commit hooks remain the final gate before commit.

## Referenced Paths For Grounding

- `teleclaude/core/next_machine/_types.py`
- `teleclaude/types/todos.py`
- `teleclaude/core/next_machine/state_io.py`
- `teleclaude/api/todo_routes.py`
- `teleclaude/core/next_machine/prepare.py`
- `teleclaude/core/next_machine/prepare_steps.py`
- `teleclaude/core/next_machine/prepare_scripts.py`
- `teleclaude/core/next_machine/phase_derivation.py`
- `teleclaude/core/next_machine/prepare_events.py`
- `teleclaude/core/next_machine/work_steps.py`
- `teleclaude/resource_validation/__init__.py`
- `teleclaude/core/roadmap.py`
- `teleclaude/core/todos_db/_show.py`
- `teleclaude/cli/telec/handlers/todo.py`
- `teleclaude/cli/telec/surface.py`
- `teleclaude/cli/tui/widgets/todo_row.py`
- `teleclaude/cli/tui/views/preparation_actions.py`
- `agents/commands/next-prepare-discovery.md`
- `agents/commands/next-prepare-gate.md`
- `docs/global/software-development/procedure/lifecycle/prepare/overview.md`
- `docs/global/software-development/procedure/lifecycle/prepare/discovery.md`
- `docs/global/software-development/procedure/lifecycle/prepare/plan-draft.md`
- `docs/global/software-development/procedure/lifecycle/prepare/readiness-gate.md`
- `docs/global/software-development/procedure/lifecycle/prepare.md`
- `docs/project/design/architecture/prepare-state-machine.md`
- `docs/project/design/architecture/lifecycle-state-machines.md`
- `docs/project/spec/jobs/next-prepare.md`
- `docs/project/spec/jobs/next-prepare-discovery.md`
- `docs/project/spec/jobs/next-prepare-draft.md`
- `docs/project/spec/jobs/next-prepare-gate.md`
- `docs/project/spec/event-vocabulary.md`
