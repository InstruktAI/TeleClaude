# Demo: mirror-runtime-isolation

## Medium

CLI + daemon logs. All validation runs locally.

## Validation

```bash
# 1) Verify canonical transcript contract — non-canonical paths rejected
pytest tests/unit/test_transcript_discovery.py -v
```

```bash
# 2) Verify non-canonical mirrors pruned by migration
pytest tests/unit/test_mirror_prune_migration.py -v
```

```bash
# 3) Verify reconciliation processes transcripts in thread isolation
pytest tests/unit/test_mirror_worker.py -v
```

```bash
# 4) Verify mirror generation and sync wrapper
pytest tests/unit/test_mirror_generator.py -v
```

```bash
# 5) Verify event-driven processor fan-out re-enabled
pytest tests/unit/test_mirror_processors.py -v
```

```bash
# 6) Snapshot WAL size before reconciliation window
ls -lh ~/.teleclaude/teleclaude.db-wal 2>/dev/null || echo "No WAL file (clean state)"
```

```bash
# 7) Restart daemon, exercise API during reconciliation
make restart && sleep 3 && make status
for i in $(seq 1 25); do
  curl -s --unix-socket /tmp/teleclaude-api.sock http://localhost/health >/dev/null
  curl -s --unix-socket /tmp/teleclaude-api.sock http://localhost/sessions >/dev/null
  curl -s --unix-socket /tmp/teleclaude-api.sock http://localhost/computers >/dev/null
done
echo "API exercised 25x during reconciliation window"
```

```bash
# 8) Check reconciliation metrics and absence of loop-lag warnings
instrukt-ai-logs teleclaude --since 5m --grep "mirror.reconciliation.complete"
instrukt-ai-logs teleclaude --since 5m --grep "API watch: loop lag"
```

```bash
# 9) Snapshot WAL size after reconciliation and compare with step 6
ls -lh ~/.teleclaude/teleclaude.db-wal 2>/dev/null || echo "No WAL file"
```

```bash
# 10) Verify mirror API and search paths still work
pytest tests/unit/test_mirror_api_routes.py -v
pytest tests/unit/test_history_mirror_search.py -v
```

```bash
# 11) Full quality gate
make lint
```

## Guided Presentation

**Step 1** proves the allowlist contract: `discover_transcripts()` returns only
canonical paths. Fixtures with `.history/` and `subagents/` paths produce zero
candidates. The `is_canonical()` function rejects non-canonical paths per agent.

**Step 2** proves the prune migration: existing non-canonical mirror rows are
removed from the database. FTS entries cleaned via triggers.

**Step 3** proves reconciliation correctness:
- Worker runs in a thread (`_reconcile_sync` via `to_thread`).
- Returns `ReconcileResult` with `discovered`, `processed`, `skipped_unchanged`,
  `skipped_no_context`, `duration_s`, `wal_before_kb`, `wal_after_kb`.
- Second pass returns `processed=0` (convergence).

**Step 4** confirms `generate_mirror_sync` works as the synchronous wrapper and
that the async `generate_mirror` delegates correctly.

**Step 5** confirms event-driven dispatch is re-enabled — the early-return guard
is removed and processor fan-out handles failures gracefully.

**Steps 6 + 9** capture pre/post WAL size for the measurement gate.

**Step 7** generates real API traffic during reconciliation to expose any
contention. The API should respond without delay.

**Step 8** is the containment proof. Expected:
- Reconciliation logs show all metric fields with `processed` trending to 0.
- Loop-lag grep returns **zero hits**.

**Measurement gate evaluation** (after 3+ cycles):
- Convergence: `processed` < 5% of `discovered` ✓/✗
- WAL growth: < 100 KB per cycle ✓/✗
- Loop lag: zero warnings ✓/✗
- Slow requests: zero `/sessions`, `/health`, `/computers` warnings ✓/✗
- Gate decision: PASS (defer DB split) / FAIL (trigger A6)

**Steps 10–11** confirm mirror API behavior and code quality are preserved.

## What the user observes

- Tests pass cleanly in steps 1–5 and 10.
- API remains responsive during reconciliation (step 7 completes without stalls).
- Reconciliation metrics show convergent behavior (high `skipped_unchanged`,
  low `processed` after initial pass).
- No loop-lag warnings appear (step 8).
- WAL growth is bounded (steps 6 vs 9).
- DB split decision recorded with measured evidence.
