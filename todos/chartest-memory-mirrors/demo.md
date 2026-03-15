# Demo: chartest-memory-mirrors

## Validation

Run the characterization suites added for the memory and mirror subsystems.

```bash
. .venv/bin/activate && pytest tests/unit/memory tests/unit/mirrors -n 1
```

Spot-check the most stateful additions: real SQLite-backed mirror storage and worker reconciliation.

```bash
. .venv/bin/activate && pytest tests/unit/mirrors/test_store.py tests/unit/mirrors/test_worker.py -n 1
```

## Guided Presentation

Start with the full `tests/unit/memory` and `tests/unit/mirrors` run and point out that every listed source file now has a matching characterization test module under `tests/unit/`.

Then run the focused mirror-store and worker block to show that the new coverage is not just mocked orchestration: it exercises real temporary SQLite schemas, FTS search, backfill cleanup, and tombstone recording.

Close by noting that the delivery changes no production code. The artifact is a safety net for future refactors of memory and mirror behavior.
