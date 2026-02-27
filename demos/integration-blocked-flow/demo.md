# Demo: integration-blocked-flow

## Validation

```bash
telec todo demo validate integration-blocked-flow
```

```bash
pytest -q -n 0 tests/integration/test_integration_blocked_flow.py
```

```bash
pytest -q -n 0 tests/unit/test_integrator_shadow_mode.py -k "blocked or resume"
```

## Guided Presentation

1. Show `integration_blocked` payload fields and diagnostics in `teleclaude/core/integration/events.py`.
2. Show follow-up linkage and idempotency behavior in `teleclaude/core/integration/blocked_followup.py`.
3. Show lease-guarded resume re-queue flow in `teleclaude/core/integration/runtime.py`.
