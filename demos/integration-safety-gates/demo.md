# Demo: integration-safety-gates

## Validation

```bash
# Finalize dispatch guardrails return deterministic machine-readable errors.
rg -n "FINALIZE_PRECONDITION_DIRTY_CANONICAL_MAIN|FINALIZE_PRECONDITION_MAIN_AHEAD|FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN" teleclaude/core/next_machine/core.py
```

```bash
# next_work enforces finalize preconditions before /next-finalize dispatch.
rg -n "check_finalize_preconditions" teleclaude/core/next_machine/core.py
```

```bash
# Post-completion finalize instructions re-check apply safety before canonical merge.
rg -n "FINALIZE APPLY SAFETY RE-CHECK|FINALIZE_PRECONDITION_DIRTY_CANONICAL_MAIN|FINALIZE_PRECONDITION_MAIN_AHEAD|FINALIZE_PRECONDITION_GIT_STATE_UNKNOWN" teleclaude/core/next_machine/core.py
```

```bash
# Regression tests cover blocked and allowed finalize paths.
pytest -q tests/unit/test_next_machine_state_deps.py tests/unit/test_next_machine_hitl.py
```

## Guided Presentation

1. Show `teleclaude/core/next_machine/core.py` and explain the shared precondition helper used before finalize dispatch.
2. Walk through the `/next-finalize` post-completion block and point out the apply-time safety re-check and explicit error codes.
3. Run the finalize-focused tests to demonstrate:
   - dirty canonical state blocks finalize dispatch,
   - main-ahead divergence blocks finalize dispatch,
   - happy-path finalize dispatch remains available when preconditions pass.
