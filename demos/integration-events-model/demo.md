# Demo: integration-events-model

## Validation

```bash
telec todo validate integration-events-model
```

```bash
rg -n "review_approved|finalize_ready|branch_pushed|idempotent|supersede" todos/integration-events-model/requirements.md
```

## Guided Presentation

1. Show the requirement contract for canonical events and readiness projection.
2. Show the implementation-plan tasks for event storage and projection logic.
3. Explain how supersession prevents stale candidates from entering integration.
