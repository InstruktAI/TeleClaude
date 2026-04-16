# prepare-lifecycle-pair-model — Requirements

## Goal

Replace the current cold-handoff prepare flow with a pair-owned preparation workflow that keeps the same two agents from requirements discovery through readiness self-validation, preserves their full context when stale grounding forces a plan refresh, reduces phase churn, and makes readiness a binary checklist instead of a numeric score.

## Scope Decision

- No split. [inferred] This is one behavior change flowing through prepare routing, readiness state, work-entry checks, operator surfaces, and stale-grounding recovery. Splitting it would leave the lifecycle internally inconsistent.

## Requirements

### R1. Pair-owned phase contract

- The prepare lifecycle must contract to the eight-phase workflow `input_assessment`, `pair_discovery`, `requirements_produced`, `pair_completion`, `grounding_check`, `re_grounding`, `prepared`, and `blocked`.
- The pair-owned preparation boundary ends at `pair_completion`.
- `grounding_check` and `re_grounding` remain separately routable mechanical phases owned by the state machine, not by the paired preparation session.
- The lifecycle must not route through separate discovery triangulation, reviewer-only prepare phases, separate spec-build phases, separate plan-draft phases, or separate gate phases. [inferred]

Verification:

- `test_prepare_phase_enum_matches_pair_model_contract`
- `test_prepare_phase_label_supports_pair_and_mechanical_states`

### R2. Human checkpoint after requirements

- `requirements_produced` is the only normal human checkpoint inside prepare.
- When the pair finishes `requirements.md`, the todo must stop in `requirements_produced` and wait for explicit human continuation.
- The machine must not auto-dispatch test-spec, planning, or readiness work while the todo is still in `requirements_produced`.

Verification:

- `test_requirements_produced_phase_waits_for_human_continue`

### R3. Same pair continues after the checkpoint

- After human continuation, the same paired preparation session remains responsible for the rest of the intelligent prepare work for that slug through `pair_completion`.
- The normal continuation path must not dispatch cold specialist workers for spec-building, plan-drafting, or gate-only work.
- The pair must carry the full preparation context forward instead of reconstructing it from intermediate handoffs.

Verification:

- `test_pair_completion_is_pair_boundary_and_grounding_becomes_mechanical`

### R4. Preparation outputs remain complete before ready

- The pair-completion path must produce all three preparation outputs before readiness can advance: grounded requirements, executable expected-failure test specifications, and an implementation plan.
- Partial completion must not be treated as ready.
- After `pair_completion`, only mechanical state-machine phases remain: `grounding_check`, optional `re_grounding`, and terminal transition to `prepared` or `blocked`.
- When stale grounding is detected after `pair_completion`, phase ownership still remains with the state machine even if the machine relays plan-refresh work back to the live pair.
- Grounding freshness remains part of the prepare contract and must still be satisfied before `prepared`.

Verification:

- `test_pair_completion_is_pair_boundary_and_grounding_becomes_mechanical`
- `test_re_grounding_messages_live_pair_before_cold_fallback`
- `test_work_step_build_started_accepts_binary_dor_completion_without_score`

### R5. DOR becomes a binary checklist

- Definition of Ready must be represented as an eight-gate checklist with per-gate PASS or DEFERRED outcomes, plus an overall completion boolean.
- Numeric DOR score and score-threshold semantics are removed from the authoritative model and from the normal prepare workflow.
- A deferred gate must record the follow-up work item that keeps the parent todo from being treated as fully ready. [inferred]

Verification:

- `test_dor_state_uses_binary_gates_and_has_no_numeric_score_fields`
- `test_validate_todo_ready_contract_uses_binary_dor_complete`

### R6. Durable state is authoritative

- Durable prepare state must determine routing.
- Artifact presence, artifact digests, and artifact timestamps may verify or stamp outputs, but they must not infer the active prepare phase or override the recorded phase.
- Phase projections shown to operators must follow the authoritative state contract rather than re-deriving phase from old artifact/review primitives.

Verification:

- `test_next_prepare_routes_from_current_pair_phase_without_phase_derivation`
- `test_prepare_phase_label_supports_pair_and_mechanical_states`

### R7. Work-entry readiness uses binary completion

- Work entry for normal todos must depend on binary readiness completion, not on a numeric score.
- Any prepare-complete validation path that decides whether a todo is ready for work must use the same binary readiness contract.

Verification:

- `test_work_step_build_started_accepts_binary_dor_completion_without_score`
- `test_validate_todo_ready_contract_uses_binary_dor_complete`

### R8. CLI, UI, and docs must reflect the new contract

- Public and operator-facing surfaces must stop advertising `--dor-score` or score-based readiness.
- Prepare labels shown in CLI/TUI status projections must represent the pair-owned and mechanical phases of the eight-state model.
- Prepare procedures, job specs, and architecture docs must describe the pair-owned workflow and must stop presenting the removed intermediate commands as active lifecycle steps.

Verification:

- `test_todo_stamp_surface_and_handler_drop_dor_score`
- `test_prepare_phase_label_supports_pair_and_mechanical_states`

### R9. Obsolete prepare commands are no longer part of the active machine

- The state machine must not dispatch `next-review-requirements`, `next-review-specs`, `next-review-plan`, `next-build-specs`, `next-prepare-draft`, or `next-prepare-gate` as part of the normal prepare path.
- Those commands may remain only as deprecated or reference material until cleanup is complete.

Verification:

- `test_pair_completion_is_pair_boundary_and_grounding_becomes_mechanical`

### R10. Breath cycle protocol

- The paired discovery process must complete at least three full breath cycles before convergence on any artifact.
- Each breath cycle consists of three ordered moves:
  Inhale: expand. Add what has not been said. Ask `what else?` and `what if?`. Do not summarize. Do not converge.
  Hold: sit with tension. Name what is forming without resolving it. Surface contradictions and unresolved questions.
  Exhale: curate the essence. Distill what was explored into concrete decisions. Guide forward with a question that opens the next layer.
- Three complete cycles is the minimum floor before the pair may begin writing an artifact. It is not the target and must not become the pair's focus. This floor exists only to prevent premature convergence, which is the pair's primary failure mode.
- If the pair is not genuinely done after three cycles, it must continue cycling until the work is actually converged.
- The pair may begin writing only when there are no material unresolved questions, contradictions, or open lines of inquiry that would undermine the artifact.
- The breath protocol applies to each major artifact: requirements, test specs, and implementation plan.
- The pair does not need to restart the cycle count between artifacts when context remains continuous.

Verification:

- `agents/commands/next-prepare-discovery.md` explicitly presents three breath cycles as a minimum floor rather than a target.
- `agents/commands/next-prepare-discovery.md` explicitly instructs the pair to continue cycling until no material unresolved questions remain before artifact writing.
- Task 5 in `implementation-plan` explicitly carries the breath-cycle rewrite into the discovery command and related lifecycle docs.

### R11. Re-grounding messages the live pair, not a cold worker

- When grounding check detects that referenced files changed after the `origin/main` merge, `re_grounding` must send the changed-file context to the live pair session rather than dispatching a new cold `next-prepare-draft` worker.
- The live pair must update `implementation-plan` against the changed files using the full context it carried from discovery through `pair_completion`.
- `next-prepare-draft` is not part of the primary re-grounding path in the pair model.
- If the live pair session is no longer alive, `re_grounding` may fall back to dispatching a fresh worker as a degraded recovery path.

Verification:

- `test_re_grounding_messages_live_pair_before_cold_fallback`
- Task 2 in `implementation-plan` rewrites `_handle_stale_grounding` to relay changed-file context to the live pair before any degraded fallback.

## Inferences

- [inferred] Score-based readiness is consumed outside the prepare machine today, so the work gate, ready-state validation, roadmap/show projections, and TUI preparation labels all have to move with the model change or the contract will drift immediately.
- [inferred] Deferring a DOR gate without a follow-up todo would recreate the ambiguity the score model had, so deferrals must be durable and attributable.
- [inferred] The pair session identity must remain discoverable after `pair_completion` so stale grounding can reuse it without forcing a context-reconstruction worker in the normal path.

## Readiness

- Definition of Ready gates 1-8 are satisfied for this preparation task.
- No external research blocker remains; the work is codebase-local.
- This todo is ready for a builder once the pair-produced artifacts are approved by the human checkpoint.
