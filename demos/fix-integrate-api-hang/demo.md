# Demo: fix-integrate-api-hang

## Validation

```bash
# Structural demo check for this slug.
telec todo demo validate fix-integrate-api-hang
```

```bash
# Prove the integrate service, route, and CLI all use the receipt-backed flow.
pytest -q tests/unit/core/operations/test_service.py tests/unit/api/test_todo_routes.py tests/unit/cli/tool_commands/test_todo.py
```

```bash
# Show the route now returns a receipt immediately through the operations service.
./.venv/bin/python - <<'PY'
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from teleclaude.api import todo_routes


async def main() -> None:
    receipt = {
        "operation_id": "demo-op",
        "kind": "todo_integrate",
        "state": "queued",
        "poll_after_ms": 250,
        "status_path": "/operations/demo-op",
        "recovery_command": "telec operations get demo-op",
    }
    operations = MagicMock()
    operations.submit_todo_integrate = AsyncMock(return_value=receipt)
    identity = SimpleNamespace(session_id="demo-session")
    with patch("teleclaude.api.todo_routes.get_operations_service", return_value=operations):
        result = await todo_routes.todo_integrate(
            slug="fix-integrate-api-hang",
            cwd="/repo",
            client_request_id="demo-request",
            identity=identity,
        )
    assert result["operation_id"] == "demo-op"
    print(result)


asyncio.run(main())
PY
```

```bash
# Show the CLI now polls the receipt until a terminal state instead of printing the first response.
./.venv/bin/python - <<'PY'
from unittest.mock import MagicMock

import teleclaude.cli.tool_commands.todo as todo_commands


responses = iter(
    [
        {"operation_id": "demo-op", "state": "running", "poll_after_ms": 1},
        {"operation_id": "demo-op", "state": "completed", "result": "integration finished"},
    ]
)

todo_commands.os.getcwd = lambda: "/tmp/project"
todo_commands.time.sleep = lambda _delay: None
todo_commands.uuid.uuid4 = lambda: "demo-request"
todo_commands.tool_api_call = lambda *_args, **_kwargs: next(responses)
todo_commands.print_json = MagicMock(side_effect=lambda payload: print(payload))
todo_commands.handle_todo_integrate(["fix-integrate-api-hang"])
PY
```

## Guided Presentation

### Medium

CLI + targeted unit tests.

### Step 1: Prove integrate submission is now receipt-first

Run the targeted unit tests. Observe the service submits `todo_integrate`
operations, the `/todos/integrate` route returns an operation receipt instead of
waiting on `next_integrate`, and the CLI polls that receipt to terminal state.

### Step 2: Show the route contract directly

Run the route snippet. Observe it prints a payload containing `operation_id`,
`state`, `poll_after_ms`, and `status_path`, which is the same durable receipt
shape used by `/todos/work`.

### Step 3: Show the CLI contract directly

Run the CLI snippet. Observe the mocked first response is `running`, but the CLI
prints only the terminal `completed` payload after polling `/operations/demo-op`.
That demonstrates the old inline contract is gone from the CLI surface as well.
