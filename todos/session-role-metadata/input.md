# session-role-metadata — Input

# Plan: Integrator Permission Profile + Job Metadata

## Context

The integration queue has a durable candidate (`icebox-physical-folder`) that's stranded because the integrator spawn guard does a naive `"integrator" in stdout` string match against all session titles. Dead sessions show up as active, blocking new integrator spawns indefinitely.

Root cause: there's no `integrator` permission profile and no structured `job` metadata on sessions. The system only knows `worker` and `orchestrator` — the integrator is spawned with no identity at all, so it runs with orchestrator-level permissions (can dispatch workers, mark phases, etc.) and is detected by grepping titles.

**Goal:** Add `integrator` as a third permission profile with its own whitelist, add a `job` field to session metadata for structured identity queries, and fix the spawn guard.

## Changes

### 1. Add `ROLE_INTEGRATOR` constant
**File:** `teleclaude/constants.py:39`

Add `ROLE_INTEGRATOR = "integrator"` after existing role constants.

### 2. Add `INTEGRATOR_ALLOWED_TOOLS` whitelist
**File:** `teleclaude/core/tool_access.py`

New whitelist after `WORKER_ALLOWED_TOOLS` (line 32):

```python
INTEGRATOR_ALLOWED_TOOLS = {
    "telec sessions tail",
    "telec sessions list",
    "telec sessions result",
    "telec sessions escalate",
    "telec operations get",
    "telec todo integrate",
}
```

The integrator needs: observe sessions (tail/list), report results, drive integration SM, and get operation status. It does NOT need: sessions run/end (no dispatching), todo work/prepare (not its job), mark-phase (not its job), agents status, channels, etc.

Note: `roadmap deliver`, `todo demo create`, and `make restart` are called by the Python state machine code inside `integration/state_machine.py`, not by the agent via API. They don't go through the clearance system.

### 3. Route integrator in `is_tool_allowed()`
**File:** `teleclaude/core/tool_access.py:95-104`

Add integrator check:
```python
def is_tool_allowed(role, tool_name, human_role=None):
    if role == ROLE_WORKER:
        return tool_name in WORKER_ALLOWED_TOOLS
    if role == ROLE_INTEGRATOR:
        return tool_name in INTEGRATOR_ALLOWED_TOOLS
    return tool_name not in _get_human_excluded_tools(human_role)
```

### 4. Recognize integrator in auth derivation
**File:** `teleclaude/api/auth.py:146`

Add `ROLE_INTEGRATOR` to valid system roles:
```python
if normalized in {ROLE_WORKER, ROLE_ORCHESTRATOR, ROLE_INTEGRATOR}:
    return normalized
```

Import `ROLE_INTEGRATOR` from constants (line 28).

### 5. Auto-derive metadata from command name in `sessions/run`
**File:** `teleclaude/api_server.py`

Add a command-to-role mapping near `WORKER_LIFECYCLE_COMMANDS` (line 139):

```python
COMMAND_ROLE_MAP: dict[str, tuple[str, str]] = {
    # command → (system_role, job)
    "next-build":                ("worker", "builder"),
    "next-bugs-fix":             ("worker", "fixer"),
    "next-review-build":         ("worker", "reviewer"),
    "next-review-plan":          ("worker", "reviewer"),
    "next-review-requirements":  ("worker", "reviewer"),
    "next-fix-review":           ("worker", "fixer"),
    "next-finalize":             ("worker", "finalizer"),
    "next-prepare-discovery":    ("worker", "discoverer"),
    "next-prepare-draft":        ("worker", "drafter"),
    "next-prepare-gate":         ("worker", "gate-checker"),
    "next-prepare":              ("orchestrator", "prepare-orchestrator"),
    "next-work":                 ("orchestrator", "work-orchestrator"),
    "next-integrate":            ("integrator", "integrator"),
}
```

In the `run_session()` endpoint (line ~1346), after building `channel_metadata`, inject session_metadata from the map:

```python
role_info = COMMAND_ROLE_MAP.get(normalized_cmd)
session_meta = None
if role_info:
    session_meta = {"system_role": role_info[0], "job": role_info[1]}
```

Pass `session_metadata=session_meta` into `self._metadata(...)`.

### 6. Switch integrator bridge to `sessions run`
**File:** `teleclaude/core/integration_bridge.py:303-315`

Replace `telec sessions start` with `telec sessions run` so the integrator flows through the same `COMMAND_ROLE_MAP` as all other dispatches:

```python
start_result = subprocess.run([
    "telec", "sessions", "run",
    "--command", "/next-integrate",
    "--project", project_path,
    "--detach",
], ...)
```

The `run_session()` endpoint derives `system_role=integrator, job=integrator` from the command name. No caller-injected metadata — the command IS the role.

### 7. Fix spawn guard — query by job metadata
**File:** `teleclaude/core/integration_bridge.py:284-296`

Replace the string match with a structured query. Add a `--job` filter to `GET /sessions` and `telec sessions list`:

**File:** `teleclaude/core/db.py` — add `get_sessions_by_metadata()`:
```python
async def get_sessions_by_metadata(
    self, key: str, value: object, include_closed: bool = False
) -> list[Session]:
    json_path = f"$.{key}"
    json_expr = func.json_extract(db_models.Session.session_metadata, json_path)
    stmt = select(db_models.Session).where(json_expr == value)
    if not include_closed:
        stmt = stmt.where(db_models.Session.closed_at.is_(None))
    ...
```

**File:** `teleclaude/api_server.py` — add `job` query param to `GET /sessions` (line 484):
```python
job: str | None = Query(None, alias="job"),
```
Filter merged sessions by `session_metadata.job == job` when provided.

**File:** `teleclaude/cli/tool_commands.py` — add `--job` flag to `handle_sessions_list()`.

Then in the bridge:
```python
list_result = subprocess.run(
    ["telec", "sessions", "list", "--all", "--job", "integrator"],
    capture_output=True, text=True, timeout=10,
)
if list_result.returncode == 0:
    sessions = json.loads(list_result.stdout)
    if sessions:  # structured check, not string match
        return None
```

### 8. Update CLI surface documentation
**File:** `teleclaude/cli/telec.py`

- Add `ROLE_INTEGRATOR` import
- Add `_SYS_INTEGRATOR = frozenset({ROLE_INTEGRATOR})`
- Update `_SYS_ALL = frozenset({ROLE_WORKER, ROLE_ORCHESTRATOR, ROLE_INTEGRATOR})`
- Update `CommandAuth` on integrator-accessible endpoints (e.g., `todo integrate` → `_SYS_INTEGRATOR`)
- Update `sessions start` CommandDef to document `--metadata` flag

## Files touched

| File | Change |
|------|--------|
| `teleclaude/constants.py` | Add `ROLE_INTEGRATOR` |
| `teleclaude/core/tool_access.py` | Add `INTEGRATOR_ALLOWED_TOOLS`, route in `is_tool_allowed()` |
| `teleclaude/api/auth.py` | Recognize integrator in `_derive_session_system_role()` |
| `teleclaude/api_server.py` | `COMMAND_ROLE_MAP`, inject metadata in `run_session()`, `--job` filter on `GET /sessions` |
| `teleclaude/cli/tool_commands.py` | `--job` flag on `sessions list` |
| `teleclaude/core/integration_bridge.py` | Switch to `sessions run`, replace string-match guard with `--job` query |
| `teleclaude/core/db.py` | Add `get_sessions_by_metadata()` query helper |
| `teleclaude/cli/telec.py` | `ROLE_INTEGRATOR`, `_SYS_INTEGRATOR`, `_SYS_ALL`, updated CommandAuth entries, `--job` flag |

## Verification

1. `make test` — existing tests pass
2. `telec sessions run --command /next-integrate --project .` → session created with `system_role=integrator, job=integrator` in metadata (derived server-side)
3. `telec sessions list --all --job integrator` → finds the integrator session
4. Verify integrator session cannot call `telec todo work` (403)
5. Verify integrator session CAN call `telec todo integrate` (200)
6. Kill integrator tmux pane, spawn a new candidate → new integrator spawns (no zombie blocking)
7. `telec sessions run --command /next-build --args test-slug --project .` → session created with `system_role=worker, job=builder` in metadata (derived server-side)
