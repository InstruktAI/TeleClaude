# Demo: hardcode-db-paths

## Validation

```bash
# Confirm zero config.database references remain in production code
grep -r "config\.database" teleclaude/ --include="*.py" && echo "FAIL: references found" || echo "PASS: zero hits"
```

```bash
# Confirm resolve_db_path is gone
grep -r "resolve_db_path" teleclaude/ --include="*.py" && echo "FAIL: references found" || echo "PASS: zero hits"
```

```bash
# Confirm dead constants are gone
grep -r "DATABASE_DIR\|DATABASE_FILENAME" teleclaude/ --include="*.py" && echo "FAIL: references found" || echo "PASS: zero hits"
```

```bash
# Confirm the three canonical constants exist in paths.py
python -c "from teleclaude.paths import MAIN_DB, MIRRORS_DB, EVENTS_DB; print('MAIN_DB:', MAIN_DB); print('MIRRORS_DB:', MIRRORS_DB); print('EVENTS_DB:', EVENTS_DB)"
```

```bash
# Full test suite
uv run pytest tests/ -x -q --timeout=10
```

## Guided Presentation

### Step 1 — Show the problem is gone

Run the grep checks. Before this change, `grep -r "config\.database"` returned
hits in `core/db/__init__.py`, `hooks/receiver/_session.py`, `mirrors/store.py`,
`mirrors/processors.py`, `daemon.py`, and `alembic/env.py`. After the change,
the result is empty — every DB consumer now resolves its path from a compile-time
constant.

### Step 2 — Show the canonical constants

```python
from teleclaude.paths import MAIN_DB, MIRRORS_DB, EVENTS_DB
```

All three are `Path` instances derived from `TELECLAUDE_HOME`. There is no runtime
resolution, no config field, and no function that can return the wrong path based
on how it was called.

### Step 3 — Show the test suite passes

Run `uv run pytest tests/ -x -q --timeout=10`. The previously xfail-marked specs
for R1–R7 are now active tests and pass green. No existing tests regressed.

### Step 4 — Show the daemon uses the right database

After `make restart`, run:

```bash
instrukt-ai-logs teleclaude --since 2m --grep mirror
```

The reconciliation log shows `failed=0` and write operations targeting
`~/.teleclaude/mirrors.db`. Before this fix, `MirrorWorker` was passed
`config.database.path` (the main DB), so reconciliation silently wrote to the
wrong file. Now it always writes to `MIRRORS_DB`.
