# Demo: deployment-migrations

## Validation

```bash
# Migration runner module exists
python -c "from teleclaude.deployment.migration_runner import discover_migrations, run_migrations; print('OK')"
```

```bash
# Example migration follows the contract
python -c "
from migrations.v1_1_0.001_example import check, migrate
assert callable(check) and callable(migrate)
print('OK: example migration follows contract')
"
```

```bash
# telec migrate --dry-run works
telec migrate --dry-run 2>&1 | grep -q "migration"
```

## Guided Presentation

### Step 1: Migration format

Show `migrations/v1.1.0/001_example.py`. Walk through the `check()`/`migrate()`
contract: check returns True if already applied (idempotency gate), migrate
performs the change and returns True on success.

### Step 2: Discovery

Run `telec migrate --dry-run --from 1.0.0 --to 1.1.0`. Observe: lists
discovered migrations in order without executing. Shows version range and
script ordering.

### Step 3: Execution

Run `telec migrate --from 1.0.0 --to 1.1.0`. Observe: runs migrations in
order, skips any where check() returns True, records state in
`~/.teleclaude/migration_state.json`.

### Step 4: Idempotency

Run the same migrate command again. Observe: all migrations skipped because
check() returns True for each. No double-apply.

### Step 5: State tracking

Show `~/.teleclaude/migration_state.json` — records which migrations have been
applied with timestamps.
