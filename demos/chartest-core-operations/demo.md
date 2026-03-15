# Demo: chartest-core-operations

## Validation

```bash
. .venv/bin/activate
pytest tests/unit/core/operations/test_service.py -q
```

## Guided Presentation

This delivery adds characterization coverage for `teleclaude/core/operations/service.py`.
Run the validation block and observe that the operations service test file passes.
The passing assertions pin the current public behavior for:

- process-wide service registration and lookup
- progress callback forwarding
- startup stale-marking and heartbeat expiry delegation
- todo-work submit dedupe, reattach, create, and retry-on-integrity-error paths
- caller/admin visibility rules for operation lookup
