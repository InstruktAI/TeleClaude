# hardcode-db-paths — Input

# Hardcode all database paths as constants

## Context

The mirrors DB refactor (06ef8962a) introduced a regression: daemon.py passed config.database.path (main DB) to MirrorWorker, which then read/wrote mirrors to the wrong database for 3 days. Root cause: DatabaseConfig and resolve_db_path() create indirection that allows callers to pass the wrong path. Additionally, processors.py passes the mirrors DB path to get_session_context() which needs the main DB, and events_signals.py queries signal tables against the main DB when they live in the events DB.

Fix: eliminate all DB path configuration. Three constants in paths.py. Zero config. Zero resolution functions.

## Changes

### Step 1: Add constants to teleclaude/paths.py
MAIN_DB_PATH = TELECLAUDE_HOME / "teleclaude.db"
MIRRORS_DB_PATH = TELECLAUDE_HOME / "mirrors.db"
EVENTS_DB_PATH = TELECLAUDE_HOME / "events.db"

### Step 2: Remove old DB constants from teleclaude/constants.py
Delete DATABASE_DIR (line 34) and DATABASE_FILENAME (line 35).

### Step 3: Remove DatabaseConfig from teleclaude/config/__init__.py
- Delete DatabaseConfig class (lines 62-66)
- Delete database: DatabaseConfig field from Config (line 333)
- Delete database=DatabaseConfig(path=...) construction (lines 825-827)
- Remove DATABASE_DIR, DATABASE_FILENAME imports from constants (lines 17-18)

### Step 4: teleclaude/core/db/__init__.py
Replace db = Db(config.database.path) with db = Db(str(MAIN_DB_PATH)). Import from teleclaude.paths.

### Step 5: teleclaude/hooks/receiver/_session.py
- Line 87: config.database.path -> str(MAIN_DB_PATH)
- Line 112: str(config.database.path) -> str(MAIN_DB_PATH)

### Step 6: teleclaude/mirrors/store.py
- Delete _MIRRORS_DB_PATH (line 20) — replaced by MIRRORS_DB_PATH from paths.py
- Delete resolve_db_path() function (lines 92-105)
- _connect_rw(db): default path becomes str(MIRRORS_DB_PATH) when db is None
- _connect_ro(db): same
- _connect_main_ro(): replace Path(config.database.path) with MAIN_DB_PATH
- get_session_context(): remove db parameter entirely. Always use _connect_main_ro(). This function queries sessions which is in the main DB — the db param was the second bug (mirrors path was passed, sessions table not found)

### Step 7: teleclaude/mirrors/processors.py
- Replace db_path = resolve_db_path() with db_path = str(MIRRORS_DB_PATH)
- Remove db=db_path from get_session_context() call (param is gone per step 6)
- Remove resolve_db_path import, add MIRRORS_DB_PATH import

### Step 8: teleclaude/mirrors/worker.py
- Remove resolve_db_path import
- __init__: self.db_path = str(Path(db).expanduser()) if db is not None else str(MIRRORS_DB_PATH)

### Step 9: teleclaude/daemon.py
- Line 499-506: MirrorWorker() with no args (already done, keep it)
- Line 281: db_path=db.db_path -> db_path=str(MAIN_DB_PATH)

### Step 10: teleclaude/events/db.py
- EventDB.__init__ default: db_path defaults to EVENTS_DB_PATH from paths.py

### Step 11: teleclaude/cli/telec/handlers/events_signals.py (bug fix)
- _load_signal_runtime(): stop returning config, return str(EVENTS_DB_PATH) instead
- Line 99: use the returned path directly (signal tables are in events DB, not main DB)

### Step 12: teleclaude/helpers/agent_cli.py
- Line 174: Path("~/.teleclaude/teleclaude.db") -> MAIN_DB_PATH

### Step 13: alembic/env.py
- Line 19: tc_config.database.path -> str(MAIN_DB_PATH), replace config import with paths import

### Step 14: Tests
- tests/conftest.py:77-82: Replace monkeypatch.setattr(tc_config.database, "path", ...) with monkeypatch.setattr("teleclaude.paths.MAIN_DB_PATH", temp_db_path). Keep the db_module.db.db_path patch (singleton already constructed at import time).
- tests/unit/mirrors/test_store.py: Delete test_resolve_db_path_* test
- tests/unit/mirrors/test_processors.py:45,92,117: Remove resolve_db_path monkeypatches (processors now uses the constant directly; get_session_context is fully mocked in these tests already)
- tests/unit/services/test_monitoring_service.py: No change needed — passes explicit db_path to constructor

### Not changing
- teleclaude/core/db/_sync.py — sync helpers keep db_path param (test isolation), production callers already being fixed at their source
- teleclaude/memory/search.py, memory/store.py, memory/context/builder.py — keep db_path param, callers fixed in step 5
- teleclaude/services/monitoring_service.py — keep db_path constructor param for test isolation
- teleclaude/core/db/_base.py — keep db_path constructor param for :memory: test support
- teleclaude/project_setup/macos_setup.py — system DBs, not ours
- teleclaude/memory/migrate_from_claude_mem.py — one-off migration script

## Verification
1. uv run pytest tests/unit/mirrors/ -x -q — mirrors tests pass
2. uv run pytest tests/ -x -q --timeout=10 — full test suite passes
3. make restart && make status — daemon healthy
4. instrukt-ai-logs teleclaude --since 2m --grep mirror — reconciliation runs with failed=0 and writes to mirrors.db
5. sqlite3 ~/.teleclaude/mirrors.db "SELECT max(updated_at) FROM mirrors;" — shows timestamps after restart
6. grep -r "config\.database" teleclaude/ --include="*.py" — zero hits
7. grep -r "resolve_db_path" teleclaude/ --include="*.py" — zero hits
8. grep -r "DATABASE_DIR\|DATABASE_FILENAME" teleclaude/ --include="*.py" — zero hits
