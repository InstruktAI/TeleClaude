# Demo: chartest-api-routes

## Validation

```bash
python - <<'PY'
from pathlib import Path

expected = [
    "test_agents_routes.py",
    "test_chiptunes_routes.py",
    "test_computers_routes.py",
    "test_data_routes.py",
    "test_event_routes.py",
    "test_jobs_routes.py",
    "test_notifications_routes.py",
    "test_operations_routes.py",
    "test_people_routes.py",
    "test_projects_routes.py",
    "test_session_access.py",
    "test_sessions_actions_routes.py",
    "test_sessions_routes.py",
    "test_settings_routes.py",
    "test_streaming.py",
    "test_todo_routes.py",
    "test_transcript_converter.py",
    "test_ws_constants.py",
    "test_ws_mixin.py",
]

base = Path("tests/unit/api")
missing = [name for name in expected if not (base / name).exists()]
print(f"expected={len(expected)} missing={len(missing)}")
if missing:
    raise SystemExit("\n".join(missing))
PY
```

```bash
pytest -q \
  tests/unit/api/test_agents_routes.py \
  tests/unit/api/test_chiptunes_routes.py \
  tests/unit/api/test_computers_routes.py \
  tests/unit/api/test_data_routes.py \
  tests/unit/api/test_event_routes.py \
  tests/unit/api/test_jobs_routes.py \
  tests/unit/api/test_notifications_routes.py \
  tests/unit/api/test_operations_routes.py \
  tests/unit/api/test_people_routes.py \
  tests/unit/api/test_projects_routes.py \
  tests/unit/api/test_session_access.py \
  tests/unit/api/test_sessions_actions_routes.py \
  tests/unit/api/test_sessions_routes.py \
  tests/unit/api/test_settings_routes.py \
  tests/unit/api/test_streaming.py \
  tests/unit/api/test_todo_routes.py \
  tests/unit/api/test_transcript_converter.py \
  tests/unit/api/test_ws_constants.py \
  tests/unit/api/test_ws_mixin.py
```

## Guided Presentation

### Step 1: Coverage map

Run the first validation block.

Observe: all 19 expected `tests/unit/api/test_*.py` files exist, matching the 19 source files listed in the todo requirements.

Why it matters: this proves the 1:1 source-to-test mapping the todo required.

### Step 2: Characterization suite

Run the pytest block.

Observe: the API characterization suite passes on the current codebase.

Why it matters: these tests pin the current public-boundary behavior of the API route modules without changing production code, giving future refactors a regression net.
