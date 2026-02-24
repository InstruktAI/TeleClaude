# Demo: ucap-canonical-contract

## Validation

```bash
# 1) Baseline health + demo artifact validation
make status
telec todo demo validate ucap-canonical-contract
```

Expected:

- Daemon reports healthy status.
- Demo artifact is structurally valid.

```bash
# 2) Contract and activity-event regression tests
pytest -q \
  tests/unit/test_agent_activity_events.py \
  tests/unit/test_agent_activity_broadcast.py \
  tests/unit/test_api_server.py
```

Expected:

- Canonical activity event mappings remain consistent.
- API broadcast compatibility behavior remains intact.

```bash
# 3) Producer path safety checks
pytest -q \
  tests/unit/test_polling_coordinator.py \
  tests/unit/test_adapter_client.py \
  tests/unit/test_threaded_output_updates.py
```

Expected:

- Output producer flow still emits updates correctly.
- No regressions in threaded/non-threaded output update behavior.

```bash
# 4) Optional observability spot-check after active session traffic
instrukt-ai-logs teleclaude --since 15m --grep "agent_activity|OUTPUT_ROUTE|delivery_scope|message_intent"
```

## Guided Presentation

1. Run baseline health and artifact validation to confirm preconditions.
2. Execute activity-event regression tests to show compatibility is preserved.
3. Execute producer-path tests to show canonical-contract adoption does not break output flow.
4. Use log grep to confirm routing metadata and activity update traces are observable at runtime.
