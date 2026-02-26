# Deployment Migrations

Deployment migrations run during version upgrades and must be idempotent.

## Directory format

- Version folder: `migrations/v{semver}/`
- Migration file: `NNN_description.py` (for example `001_rename_config_key.py`)

Example layout:

```text
migrations/
  v1.1.0/
    001_example.py
  v1.2.0/
    001_another_change.py
```

## Migration contract

Every migration file must expose exactly two callables:

- `check() -> bool`: return `True` when the migration effect is already present.
- `migrate() -> bool`: apply the change and return `True` on success.

Rules:

- Keep migrations idempotent.
- `check()` must be fast and side-effect free.
- `migrate()` may mutate local state but must not depend on network access.
- Return `False` to signal a handled failure; raising an exception is also treated as failure.

The runner executes migrations in ascending order by version, then by numeric prefix.
