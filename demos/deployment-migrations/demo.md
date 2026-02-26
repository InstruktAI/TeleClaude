# Demo: deployment-migrations

## Validation

```bash
# Migration runner module exists
python -c "from teleclaude.deployment.migration_runner import discover_migrations, run_migrations; print('OK')"
```

```bash
# Version utilities work
python -c "
from teleclaude.deployment import parse_version, version_cmp
assert parse_version('v1.2.3') == (1, 2, 3)
assert version_cmp('1.0.0', '1.1.0') == -1
print('OK: version utilities')
"
```

```bash
# Example migration follows the contract
python -c "
import importlib.util
from pathlib import Path

example_path = Path('migrations') / 'v1.1.0' / '001_example.py'
spec = importlib.util.spec_from_file_location('deployment_migration_example', example_path)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert callable(getattr(module, 'check', None))
assert callable(getattr(module, 'migrate', None))
print('OK: example migration follows contract')
"
```

## Guided Presentation

### Step 1: Migration format

Show `migrations/v1.1.0/001_example.py`. Walk through `check()`/`migrate()`
contract: check returns True if already applied, migrate performs the change.

### Step 2: Discovery

```python
from teleclaude.deployment.migration_runner import discover_migrations
migrations = discover_migrations("1.0.0", "1.1.0")
print(migrations)  # [(version, script_path), ...]
```

### Step 3: Execution (programmatic)

```python
from teleclaude.deployment.migration_runner import run_migrations
result = run_migrations("1.0.0", "1.1.0", dry_run=True)
print(result)  # {migrations_run: 0, migrations_skipped: 0, error: None, planned_migrations: [...]}
```

### Step 4: Idempotency

Run again — all skipped because `check()` returns True.

### Step 5: State tracking

Show `~/.teleclaude/migration_state.json` — records applied migrations.
