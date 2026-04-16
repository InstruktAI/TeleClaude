# prepare-lifecycle-pair-model — Test Specs

The executable spec file for this todo is:

- `tests/unit/core/next_machine/test_prepare_lifecycle_pair_model_specs.py`

All tests in that file stay xfail-marked until the pair-model implementation lands. The builder removes the xfail marker first, then makes the tests green without weakening any assertions. The file must be extended with any missing xfail cases required by this inventory, including the live-pair re-grounding contract.

## Spec Inventory

- `test_prepare_phase_enum_matches_pair_model_contract`
  Proves the prepare phase set contracts to the eight-state pair-model workflow and drops the old intermediate phases.

- `test_requirements_produced_phase_waits_for_human_continue`
  Proves the post-requirements checkpoint is a real wait state and does not auto-dispatch more preparation work.

- `test_next_prepare_routes_from_current_pair_phase_without_phase_derivation`
  Proves prepare routing uses authoritative durable state instead of re-deriving phase from artifact/review primitives.

- `test_pair_completion_is_pair_boundary_and_grounding_becomes_mechanical`
  Proves `pair_completion` is the end of pair-owned work and that the machine advances into mechanical grounding flow without dispatching more intelligent prepare workers.

- `test_re_grounding_messages_live_pair_before_cold_fallback`
  Proves stale grounding relays changed-file context to the live pair session, does not dispatch `next-prepare-draft` while that pair is alive, and only falls back to a fresh worker when no live pair session can be found.

- `test_dor_state_uses_binary_gates_and_has_no_numeric_score_fields`
  Proves the readiness model is a checklist with completion semantics, not a numeric score/status pair.

- `test_work_step_build_started_accepts_binary_dor_completion_without_score`
  Proves work entry can proceed from binary readiness completion without any numeric DOR score.

- `test_validate_todo_ready_contract_uses_binary_dor_complete`
  Proves ready-state validation keys off binary readiness instead of the old score threshold.

- `test_todo_stamp_surface_and_handler_drop_dor_score`
  Proves the CLI surface and stamp handler stop advertising or accepting `--dor-score`.

- `test_prepare_phase_label_supports_pair_and_mechanical_states`
  Proves TUI preparation labels align with both the pair-owned and mechanical phases of the new model.

## Run Target

- `pytest tests/unit/core/next_machine/test_prepare_lifecycle_pair_model_specs.py -q`

## Coverage Intent

- Core routing and state contract
- Pair/mechanical boundary at `pair_completion`
- Re-grounding relay/fallback behavior that preserves pair context
- Readiness model and work-entry guard
- CLI stamp/help surface
- TUI phase projection

No spec assertions rely on human-facing prose. Command-token assertions are limited to execution-significant slash-command names.
