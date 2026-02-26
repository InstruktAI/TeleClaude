# Demo: integration-events-model

## Validation

```bash
# Targeted event-model and workflow tests
pytest \
  tests/unit/test_integration_events.py \
  tests/unit/test_next_machine_hitl.py \
  tests/unit/test_next_machine_state_deps.py \
  tests/unit/test_todo_routes.py -q
```

```bash
# Inspect persisted canonical integration events in SQLite
sqlite3 teleclaude.db "
SELECT event_type, slug, branch, sha
FROM integration_events
ORDER BY id DESC
LIMIT 10;
"
```

```bash
# Inspect readiness projection for a candidate slug
python - <<'PY'
from teleclaude.core.integration_events import load_projection_for_slug

slug = "integration-events-model"
rows = load_projection_for_slug("teleclaude.db", slug)
print(rows)
PY
```

## Guided Presentation

Medium: CLI + SQLite inspection.

1. Trigger the targeted test suite and show all event/projection tests passing.
2. Query `integration_events` and point out rows for `review_approved`,
   `finalize_ready`, and `branch_pushed` with canonical fields present.
3. Query readiness projection for a sample slug/candidate and show:
   - missing predicates when incomplete,
   - `READY` only when all required events and alignment checks pass.
4. Demonstrate supersession: emit a newer `finalize_ready` for the same slug
   and show the older candidate is marked superseded/not-ready.
5. Confirm finalize safety gates are unchanged by referencing existing
   `next-finalize` instruction checks in tests.
