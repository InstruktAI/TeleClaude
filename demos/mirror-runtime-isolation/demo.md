# Demo: mirror-runtime-isolation

## Validation

```bash
pytest -n 0 \
  tests/unit/test_transcript_discovery.py \
  tests/unit/test_mirror_generator.py \
  tests/unit/test_mirror_worker.py \
  tests/unit/test_mirror_processors.py \
  tests/unit/test_mirror_store.py \
  tests/unit/test_mirror_prune_migration.py \
  tests/unit/test_history_mirror_search.py \
  tests/unit/test_mirror_api_routes.py
```

```bash
pytest -n 0 \
  tests/unit/test_mirror_worker.py::test_run_once_offloads_reconciliation_to_thread \
  tests/unit/test_mirror_worker.py::test_reconcile_sync_tombstones_empty_transcripts_until_the_file_changes \
  tests/unit/test_mirror_worker.py::test_backfill_sync_removes_stale_rows_and_rebuilds_canonical_rows
```

## Guided Presentation

1. Run the full mirror-focused pytest block. It proves the canonical discovery contract, prune migration, source-identity migration, event dispatch path, search/API accessors, and worker reconciliation flow together.
2. Call out the worker-specific block. It shows three behaviors that matter to the incident: `run_once()` offloads to a thread, empty transcripts tombstone instead of churning, and backfill removes stale rows before rebuilding canonical mirrors.
3. Open [`teleclaude/mirrors/worker.py`](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mirror-runtime-isolation/teleclaude/mirrors/worker.py) and [`teleclaude/mirrors/store.py`](/Users/Morriz/Workspace/InstruktAI/TeleClaude/trees/mirror-runtime-isolation/teleclaude/mirrors/store.py) to connect the observed tests to the implemented runtime boundaries: canonical source identity, thread-isolated reconciliation, tombstones, and structured reconciliation metrics.
