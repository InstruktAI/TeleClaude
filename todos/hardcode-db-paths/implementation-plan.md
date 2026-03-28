# hardcode-db-paths — Implementation Plan

## Atomicity verdict

**Atomic.** All steps touch one coherent behavior change: eliminating DB path
indirection via `DatabaseConfig` and `resolve_db_path()`. Every file is known,
every change is mechanical substitution. Splitting would create a half-working
codebase between steps.

## Task overview

| #   | Task                                                                   | xfail specs satisfied                              |
| --- | ---------------------------------------------------------------------- | -------------------------------------------------- |
| 1   | Add DB constants to `paths.py`                                         | R1 (`tests/unit/test_paths.py`)                    |
| 2   | Replace `config.database.path` in all non-mirrors consumers            | R7, R5, partial R2 consumers                       |
| 3   | Refactor mirrors store (remove indirection, fix `get_session_context`) | R3, R4 (store specs)                               |
| 4   | Update mirrors processors and worker                                   | R3, R4 (processors spec)                           |
| 5   | Remove `DatabaseConfig` and dead constants                             | R2 (config spec)                                   |
| 6   | Update tests for isolation and removed APIs                            | R6, R4, R3 (conftest, test_store, test_processors) |

---

## Task 1 — Add `MAIN_DB`, `MIRRORS_DB`, `EVENTS_DB` to `paths.py`

**File:** `teleclaude/paths.py`

**What:** Append three constants below the existing `RUNTIME_SETTINGS_PATH` line:

```python
MAIN_DB = TELECLAUDE_HOME / "teleclaude.db"
MIRRORS_DB = TELECLAUDE_HOME / "mirrors.db"
EVENTS_DB = TELECLAUDE_HOME / "events.db"
```

**Why:** These are the single source of truth for all three database paths. Every
subsequent task imports from here. Adding them first makes the rest of the plan
a series of simple import swaps. The constant names are `MAIN_DB`, `MIRRORS_DB`,
`EVENTS_DB` — confirmed against the xfail test specs in `test_paths.py`.

**Verification:** Remove the `@pytest.mark.xfail` markers from all four tests in
`tests/unit/test_paths.py`:

- `test_main_db_constant_exists_and_derives_from_teleclaude_home`
- `test_mirrors_db_constant_exists_and_derives_from_teleclaude_home`
- `test_events_db_constant_exists_and_derives_from_teleclaude_home`
- `test_db_constants_are_path_instances`

Run: `uv run pytest tests/unit/test_paths.py -x -q` → GREEN.

---

## Task 2 — Replace `config.database.path` in all non-mirrors consumers

**Files:** six files (detailed below). None of these is mirrors — mirrors gets its own tasks.

**Why:** All these sites read `config.database.path` to get a DB path at runtime.
That indirection is exactly the class of bug that caused the regression. Replacing
with compile-time constants eliminates the failure mode entirely. All imports
resolve after Task 1 adds the constants.

### 2a — `teleclaude/core/db/__init__.py`

Line 45:

```python
# Before
db = Db(config.database.path)

# After
from teleclaude.paths import MAIN_DB
db = Db(str(MAIN_DB))
```

Remove `from teleclaude.config import config` if it is used only for
`config.database.path` in this file — verify before removing.

### 2b — `teleclaude/hooks/receiver/_session.py`

Two usages. Add `MAIN_DB` to the existing `from teleclaude.paths import` line (line 24):

```python
from teleclaude.paths import MAIN_DB, SESSION_MAP_PATH
```

- `_create_sync_engine` (≈ line 87): `f"sqlite:///{config.database.path}"` →
  `f"sqlite:///{MAIN_DB}"`
- `_get_memory_context` (≈ line 112): `db_path = str(config.database.path)` →
  `db_path = str(MAIN_DB)`

Keep `from teleclaude.config import config` — it is used for `config.computer.*`
and other fields elsewhere in this file.

### 2c — `teleclaude/events/db.py`

`EventDB.__init__` default parameter (line 158):

```python
# Before
def __init__(self, db_path: str | Path = "~/.teleclaude/events.db") -> None:

# After (import added at module top):
from teleclaude.paths import EVENTS_DB
...
def __init__(self, db_path: str | Path = EVENTS_DB) -> None:
```

The `db_path` parameter is retained for test isolation — callers that need a temp
path still pass it explicitly. Only the default changes.

### 2d — `teleclaude/cli/telec/handlers/events_signals.py` (R5)

Bug fix: signal tables live in `events.db`, not `teleclaude.db`.

Update `_load_signal_runtime()` to return the events DB path via lazy import
(preserving the existing `importlib.import_module` pattern so the xfail test can
patch `sys.modules["teleclaude.paths"]` with a sentinel):

```python
def _load_signal_runtime() -> tuple[Any, str, Any]:
    aiosqlite = importlib.import_module("aiosqlite")
    paths = importlib.import_module("teleclaude.paths")
    signal_db = importlib.import_module("teleclaude.events.signal.db").SignalDB
    return aiosqlite, str(paths.EVENTS_DB), signal_db
```

Update `_handle_signals_status` to unpack the path:

```python
async def _query() -> None:
    aiosqlite, db_path, signal_db = _load_signal_runtime()
    async with aiosqlite.connect(db_path) as conn:
        ...
```

**Why:** A top-level import of `paths.EVENTS_DB` would defeat the test's
`patch.dict(sys.modules, ...)` approach. The lazy pattern is already established
in this file.

**Verification:** Remove the `@pytest.mark.xfail` marker from
`test_handle_signals_status_connects_to_events_db` in
`tests/unit/cli/telec/handlers/test_events_signals.py`. Run that file — all tests GREEN.

### 2e — `teleclaude/helpers/agent_cli.py`

`db_available` function (≈ line 174):

```python
# Before
db_path = Path("~/.teleclaude/teleclaude.db").expanduser()

# After
from teleclaude.paths import MAIN_DB  # add to existing imports at top of file
...
db_path = MAIN_DB
```

The rest of `db_available` (the `sqlite3.connect(str(db_path), ...)` call) works
unchanged since `MAIN_DB` is a `Path` — `str(db_path)` still produces the correct
absolute path string.

### 2f — `alembic/env.py` (R7)

```python
# Before
from teleclaude.config import config as tc_config
...
config.set_main_option("sqlalchemy.url", f"sqlite:///{tc_config.database.path}")

# After
from teleclaude.paths import MAIN_DB
...
config.set_main_option("sqlalchemy.url", f"sqlite:///{MAIN_DB}")
```

Remove `from teleclaude.config import config as tc_config`. The `db_models` import
and `SQLModel` reference are unaffected.

**Verification:** Remove the `@pytest.mark.xfail` markers from all three tests in
`tests/unit/test_alembic_env.py`. Run — GREEN.

### 2g — `teleclaude/daemon.py`

Add `from teleclaude.paths import MAIN_DB` to the daemon's imports.

Two fixes:

1. **MaintenanceService construction** (≈ line 281):
   `db_path=db.db_path` → `db_path=str(MAIN_DB)`.

2. **Mirror worker startup** (≈ lines 499–506): The conditional guard on
   `config.database.path` being non-empty is dead code once constants always exist.
   Replace with:
   ```python
   mirror_worker = MirrorWorker()
   self.mirror_worker_task = asyncio.create_task(mirror_worker.run(), name="mirror-worker")
   self._track_background_task(self.mirror_worker_task, "mirror-worker")
   logger.info("Mirror worker started")
   ```

**Why:** The original guard existed because `config.database.path` could be unset.
A compile-time constant cannot be absent. The guard was a defense-in-depth around
a configuration gap this refactor closes.

---

## Task 3 — Refactor mirrors store (R3 + R4)

**File:** `teleclaude/mirrors/store.py`

**Why:** `_MIRRORS_DB_PATH` duplicates `MIRRORS_DB`. `resolve_db_path()` is the
indirection layer that allowed callers to pass the wrong path — the direct root
cause of the mirrors regression. `get_session_context`'s `db` parameter was the
secondary bug: `processors.py` passed the mirrors DB to a function that queries
the sessions table which lives in the main DB.

### 3a — Remove `_MIRRORS_DB_PATH` and `resolve_db_path()`

- Delete line 20: `_MIRRORS_DB_PATH = Path("~/.teleclaude/mirrors.db").expanduser()`
- Delete the `resolve_db_path()` function (lines 92–105)
- Add to imports: `from teleclaude.paths import MAIN_DB, MIRRORS_DB`
- Remove `from teleclaude.config import config` (no longer used after fixing `_connect_main_ro`)

### 3b — Fix `_connect_rw` and `_connect_ro` defaults

Both functions keep the `db` parameter for test isolation. Replace the
`resolve_db_path(db)` call with inline path resolution defaulting to `MIRRORS_DB`:

```python
def _connect_rw(db: object | None = None) -> sqlite3.Connection:
    if db is None:
        path = str(MIRRORS_DB)
    elif isinstance(db, Path):
        path = str(db.expanduser())
    elif isinstance(db, str):
        path = str(Path(db).expanduser())
    else:
        db_path_attr = getattr(db, "db_path", None)
        path = str(db_path_attr) if isinstance(db_path_attr, str) else str(MIRRORS_DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    _ensure_schema(conn, path)
    return conn
```

Apply the same inline resolution to `_connect_ro` (the existing `resolve_db_path`
call and the `str(path) not in _schema_initialized` check stay; only the path
resolution source changes).

**Why:** R6 requires that test code can still pass explicit temp paths via `db=`.
The inline resolution preserves all code paths that `resolve_db_path` covered,
just without the indirection.

### 3c — Fix `_connect_main_ro`

```python
def _connect_main_ro() -> sqlite3.Connection:
    path = MAIN_DB.expanduser().resolve()
    uri = f"file:{quote(str(path))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn
```

### 3d — Remove `db` parameter from `get_session_context` (R4)

```python
def get_session_context(
    *,
    session_id: str | None = None,
    transcript_path: str | None = None,
    # db parameter removed — always queries the main DB
) -> SessionMirrorContext | None:
    ...
    try:
        with _connect_main_ro() as conn:
            row = conn.execute(sql, params).fetchone()
    except sqlite3.OperationalError as exc:
        ...
```

Remove the conditional `conn_fn` logic entirely. Always use `_connect_main_ro()`.

**Verification:** Remove the `@pytest.mark.xfail` markers from:

- `TestResolveDbPathRemoved.test_resolve_db_path_does_not_exist_on_store_module`
- `TestResolveDbPathRemoved.test_mirrors_db_path_module_constant_does_not_exist`

in `tests/unit/mirrors/test_store.py`.

Remove from `tests/unit/mirrors/test_processors.py`:

- `TestGetSessionContextDbParamRemoved.test_get_session_context_has_no_db_parameter`

Run: `uv run pytest tests/unit/mirrors/test_store.py -x -q` → GREEN.

---

## Task 4 — Update mirrors processors and worker (R3 consumers)

### 4a — `teleclaude/mirrors/processors.py`

Replace `resolve_db_path()` usage with `MIRRORS_DB`:

```python
# Remove:
from .store import get_session_context, resolve_db_path

# Add:
from teleclaude.paths import MIRRORS_DB
from .store import get_session_context

# In process_mirror_event:
db_path = str(MIRRORS_DB)
context = get_session_context(session_id=event.session_id, transcript_path=event.transcript_path)
# (db= argument removed)
```

Keep `from teleclaude.config import config` — line 109 uses `config.computer.name`
as a fallback for the computer field.

**Why:** `resolve_db_path` does not exist after Task 3. `get_session_context` drops
`db=` after Task 3d. Both usages must update in the same commit or processors.py
fails to import.

**Verification:** Remove the `@pytest.mark.xfail` marker from
`TestGetSessionContextDbParamRemoved.test_process_mirror_event_does_not_use_resolve_db_path`.

### 4b — `teleclaude/mirrors/worker.py`

Replace `resolve_db_path` import and `__init__` usage:

```python
# Remove from store import:
#   resolve_db_path

# Add:
from teleclaude.paths import MIRRORS_DB

# __init__:
def __init__(self, db: object | None = None, interval_s: int = RECONCILE_INTERVAL_S) -> None:
    if db is None:
        self.db_path = str(MIRRORS_DB)
    elif isinstance(db, str):
        self.db_path = str(Path(db).expanduser())
    else:
        self.db_path = str(Path(str(db)).expanduser())
    self.interval_s = interval_s
```

Keep `db` parameter — tests and callers may still pass an explicit temp path.

**Verification:** `uv run pytest tests/unit/mirrors/test_worker.py -x -q` → GREEN.

---

## Task 5 — Remove `DatabaseConfig` and dead constants (R2)

### 5a — `teleclaude/constants.py`

Delete:

```python
DATABASE_DIR = str(Path("~/.teleclaude").expanduser())  # line 34
DATABASE_FILENAME = "teleclaude.db"                     # line 35
```

**Why:** These constants existed solely to construct `DatabaseConfig.path`. After
Tasks 2–4, no production code references them.

### 5b — `teleclaude/config/__init__.py`

Four removals:

1. Remove `DATABASE_DIR` and `DATABASE_FILENAME` from the
   `from teleclaude.constants import ...` block (≈ lines 17–18).

2. Delete the `DatabaseConfig` dataclass (≈ lines 62–66).

3. Remove `database: DatabaseConfig` field from the `Config` dataclass (≈ line 333).

4. Remove the `database=DatabaseConfig(path=f"{DATABASE_DIR}/{DATABASE_FILENAME}")`
   construction from the factory function (≈ lines 825–827).

**Why:** With all consumers migrated, keeping the class would leave an orphaned
config surface. Tests in conftest still patch it before Task 6 — remove the class
only after the conftest patch is updated.

**Order within Task 5:** Do 5b after Task 6 (the conftest update) or ensure 5a/5b
are committed in the same atomic commit as Task 6. If you commit 5b before 6a, the
conftest tries to patch `tc_config.database` which no longer exists and all tests
fail.

**Practical order:** Do Task 6 first (or merge Tasks 5 and 6 into one commit).

**Verification:** Remove the `@pytest.mark.xfail` markers from all four tests in
`tests/unit/config/test_database_config_removed.py`. Run — GREEN.

**Success check:**

```bash
grep -r "config\.database" teleclaude/ --include="*.py"
# Expected: zero hits
grep -r "DATABASE_DIR\|DATABASE_FILENAME" teleclaude/ --include="*.py"
# Expected: zero hits
```

---

## Task 6 — Update tests for isolation and removed APIs (R6)

**Note:** Do this in the same commit as Task 5b. The conftest patch must not try
to set `tc_config.database.path` on a `Config` object that no longer has a
`database` attribute.

### 6a — `tests/conftest.py` — `_isolate_test_environment` fixture

Replace the block at ≈ lines 77–82:

```python
# Before
try:
    from teleclaude.config import config as tc_config
    monkeypatch.setattr(tc_config.database, "path", str(temp_db_path))
except Exception:
    pass

# After
try:
    import teleclaude.paths as paths_module
    monkeypatch.setattr(paths_module, "MAIN_DB", temp_db_path)
except Exception:
    pass
```

Keep the `db_module.db.db_path` patch (lines 84–89) unchanged — the `Db` singleton
is constructed at import time with the path baked into the object; patching
`MAIN_DB` alone does not retroactively update the already-constructed singleton.

**Why:** Patching the module-level `Path` constant is the established isolation
pattern in this codebase (see `_isolate_tui_state` patching `paths.TUI_STATE_PATH`).

### 6b — `tests/unit/mirrors/test_store.py`

1. **Delete** the entire `TestResolveDbPath` class (≈ lines 63–69). It tested
   `resolve_db_path()` which no longer exists.

2. **Fix** `test_state_tombstones_and_session_context_round_trip`: add
   `monkeypatch: pytest.MonkeyPatch` to the signature, and before the
   `get_session_context` call:

   ```python
   import teleclaude.paths as paths_module
   monkeypatch.setattr(paths_module, "MAIN_DB", db_path)
   context = store_module.get_session_context(session_id="session-1")
   ```

   (Drop the `db=str(db_path)` argument since R4 removes that parameter.)

   **Why:** `get_session_context` now unconditionally opens `MAIN_DB`. The test
   must redirect `MAIN_DB` to the temp path so the session row inserted in the
   same test is visible.

### 6c — `tests/unit/mirrors/test_processors.py`

Three existing (non-xfail) tests patch `resolve_db_path` and use a `db=None`
keyword in the `get_session_context` mock. Both are now obsolete:

In each of:

- `test_process_mirror_event_generates_mirror_with_fallback_computer_name`
- `test_process_mirror_event_skips_unknown_agent_values`
- `test_process_mirror_event_passes_expanded_session_context`

Do:

- Remove: `monkeypatch.setattr(processors_module, "resolve_db_path", lambda: "mirrors.sqlite")`
- Update the `get_session_context` mock lambda: remove `db=None` from its parameter list

**Verification:** Remove the `@pytest.mark.xfail` marker from
`TestMonkeypatchMigration.test_process_mirror_event_uses_paths_mirrors_db_not_config`.

Run: `uv run pytest tests/unit/mirrors/ -x -q` → GREEN.

---

## Final verification

```bash
# R2 success criterion
grep -r "config\.database" teleclaude/ --include="*.py"   # zero hits

# R3 success criterion
grep -r "resolve_db_path" teleclaude/ --include="*.py"    # zero hits

# R2 success criterion
grep -r "DATABASE_DIR\|DATABASE_FILENAME" teleclaude/ --include="*.py"  # zero hits

# Full test suite
uv run pytest tests/ -x -q --timeout=10                  # all pass

# Pre-commit
pre-commit run --all-files                                # pass
```
