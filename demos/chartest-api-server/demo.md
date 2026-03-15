# Demo: chartest-api-server

## Validation

```bash
# Run the characterization tests for api_models and api_server
./.venv/bin/pytest tests/unit/test_api_models.py tests/unit/test_api_server.py -q
```

```bash
# Confirm both test files exist with expected test counts
./.venv/bin/pytest tests/unit/test_api_models.py tests/unit/test_api_server.py --collect-only -q
```

## Guided Presentation

The delivery adds characterization tests for two API modules:

1. `tests/unit/test_api_models.py` — pins request/response model validation (field constraints,
   model validators, from_core mapping, defaults, extra-field rejection).

2. `tests/unit/test_api_server.py` — pins APIServer behavioral methods without heavy constructor
   infrastructure: `_get_fd_count`, `_metadata`, `_cleanup_socket`, `_dump_stacks` cooldown,
   `set_on_server_exit`, `_on_server_task_done`, and all four event handler dispatch methods.

Run the unit tests to see all tests pass green.
