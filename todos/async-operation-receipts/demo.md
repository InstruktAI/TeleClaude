# Demo: async-operation-receipts

## Validation

```bash
# Structural demo check for this slug.
telec todo demo validate async-operation-receipts --project-root .
```

```bash
# Prove the receipt-first API and durable operation service contracts.
pytest -q tests/unit/test_todo_operations_api.py tests/unit/test_operations_service.py
```

```bash
# Prove the CLI polling/recovery surface and the explicit operations lookup command.
pytest -q tests/unit/cli/test_tool_commands.py::test_handle_operations_get_fetches_status
```

## Guided Presentation

### Medium

CLI + targeted unit tests.

### Step 1: Prove the API is receipt-first

Run the targeted API and operations-service tests. Observe that `/todos/work`
returns `202` with an `operation_id`, the submit path does not wait on
`next_work()`, and duplicate submissions reattach instead of creating duplicate
execution.

### Step 2: Show the recovery handle is a first-class CLI contract

Run the targeted CLI test for `telec operations get`. Observe that the CLI has
an explicit operation-inspection command instead of relying on hidden tmux
delivery or a single long-lived HTTP response.

### Step 3: Narrate the live operator flow

Explain the intended live flow:

1. `telec todo work <slug>` submits work and receives a durable receipt.
2. The CLI auto-polls `/operations/{operation_id}` until completion.
3. If the wrapper is interrupted, `telec operations get <operation_id>` resumes
   inspection without re-running `next_work()`.
