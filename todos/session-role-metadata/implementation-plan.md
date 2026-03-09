# Implementation Plan: session-role-metadata

## Overview

Introduce `integrator` as a first-class session permission profile, add structured `job`
metadata to command-driven session creation, and replace the integrator spawn guard's
title-text heuristic with a structured metadata query.

The change flows through one chain: constant definition -> tool access whitelist ->
auth derivation -> server-side metadata injection -> session listing filter -> spawn
guard replacement -> CLI surface alignment.

## Tasks

### Task 1: Add `ROLE_INTEGRATOR` constant

**File(s):** `teleclaude/constants.py`

- [ ] Add `ROLE_INTEGRATOR = "integrator"` after existing `ROLE_WORKER` (line 39)

**Why:** Every downstream component references role constants. A shared constant
prevents string literals from drifting.

**Verification:** Import succeeds; existing tests still pass.

---

### Task 2: Add `INTEGRATOR_ALLOWED_TOOLS` whitelist and route in `is_tool_allowed()`

**File(s):** `teleclaude/core/tool_access.py`, `tests/unit/test_role_tools.py`

- [ ] Import `ROLE_INTEGRATOR` from constants
- [ ] Add `INTEGRATOR_ALLOWED_TOOLS` set after `WORKER_ALLOWED_TOOLS` (line 32):
  ```
  "telec sessions tail", "telec sessions list", "telec sessions result",
  "telec sessions escalate", "telec operations get", "telec todo integrate"
  ```
- [ ] Add integrator branch in `is_tool_allowed()` between the worker check and the
  human-role fallback:
  ```python
  if role == ROLE_INTEGRATOR:
      return tool_name in INTEGRATOR_ALLOWED_TOOLS
  ```
- [ ] Write tests in `tests/unit/test_role_tools.py`:
  - `test_integrator_whitelist_allows_integrate`
  - `test_integrator_whitelist_blocks_dispatch`
  - `test_integrator_whitelist_blocks_orchestration`
  - `test_integrator_allowed_tools_complete`

**Why:** The integrator needs to observe sessions, report results, and drive the
integration state machine — but must NOT dispatch sessions, mark phases, or use
orchestrator commands. A whitelist (matching the worker pattern) enforces this.

**Verification:** New tests pass; existing role tests remain green.

---

### Task 3: Recognize integrator in auth derivation

**File(s):** `teleclaude/api/auth.py`, `tests/unit/test_api_auth.py`

- [ ] Import `ROLE_INTEGRATOR` from constants (add to existing import block ~line 28)
- [ ] In `_derive_session_system_role()` (line 146), extend the valid-role set:
  ```python
  if normalized in {ROLE_WORKER, ROLE_ORCHESTRATOR, ROLE_INTEGRATOR}:
      return normalized
  ```
- [ ] Write test `test_derive_session_system_role_integrator` — a session with
  `session_metadata={"system_role": "integrator"}` and no `working_slug` derives
  `"integrator"`

**Why:** Without this, a session with `system_role=integrator` in metadata would fall
through to the worker heuristic or return None, making tool clearance act as
orchestrator-level (no restrictions).

**Verification:** New test passes; existing auth tests remain green.

---

### Task 4: Add `COMMAND_ROLE_MAP` and inject session metadata in `run_session()`

**File(s):** `teleclaude/api_server.py`, `tests/unit/test_run_session_metadata.py`

- [ ] Add `COMMAND_ROLE_MAP` dict near `WORKER_LIFECYCLE_COMMANDS` (line 139):
  ```python
  COMMAND_ROLE_MAP: dict[str, tuple[str, str]] = {
      "next-build":               ("worker", "builder"),
      "next-bugs-fix":            ("worker", "fixer"),
      "next-review-build":        ("worker", "reviewer"),
      "next-review-plan":         ("worker", "reviewer"),
      "next-review-requirements": ("worker", "reviewer"),
      "next-fix-review":          ("worker", "fixer"),
      "next-finalize":            ("worker", "finalizer"),
      "next-prepare-discovery":   ("worker", "discoverer"),
      "next-prepare-draft":       ("worker", "drafter"),
      "next-prepare-gate":        ("worker", "gate-checker"),
      "next-prepare":             ("orchestrator", "prepare-orchestrator"),
      "next-work":                ("orchestrator", "work-orchestrator"),
      "next-integrate":           ("integrator", "integrator"),
  }
  ```
- [ ] In `run_session()` endpoint, after building `channel_metadata` (~line 1345),
  derive and inject `session_metadata`:
  ```python
  role_info = COMMAND_ROLE_MAP.get(normalized_cmd)
  session_meta: dict[str, str] | None = None
  if role_info:
      session_meta = {"system_role": role_info[0], "job": role_info[1]}
  ```
- [ ] Pass `session_metadata=session_meta` into the `self._metadata(...)` call
  (add `session_metadata=session_meta` kwarg at line 1346)
- [ ] Write tests in `tests/unit/test_run_session_metadata.py`:
  - `test_run_session_derives_worker_metadata` — `/next-build` command produces
    `session_metadata={"system_role": "worker", "job": "builder"}`
  - `test_run_session_derives_integrator_metadata` — `/next-integrate` command produces
    `session_metadata={"system_role": "integrator", "job": "integrator"}`
  - `test_run_session_unknown_command_no_metadata` — unrecognized command passes
    `session_metadata=None`

**Why:** Server-side derivation from the command name means callers cannot inject
arbitrary roles. The command IS the identity.

**Verification:** New tests pass; existing endpoint tests remain green.

---

### Task 5: Add `--job` filter to session listing (API + CLI)

**File(s):** `teleclaude/api_server.py`, `teleclaude/cli/tool_commands.py`,
`teleclaude/cli/telec.py`, `tests/unit/test_session_list_job_filter.py`

- [ ] In `list_sessions()` endpoint (~line 482), add `job` query parameter:
  ```python
  job: str | None = Query(None, alias="job"),
  ```
- [ ] After merge+filter logic (before DTO conversion, ~line 535), filter when provided:
  ```python
  if job:
      merged = [
          s for s in merged
          if isinstance(s.session_metadata, dict)
          and s.session_metadata.get("job") == job
      ]
  ```
- [ ] In `handle_sessions_list()` (~line 110 of tool_commands.py), add `--job` flag
  parsing:
  ```python
  job_filter = None
  for i, arg in enumerate(args):
      if arg == "--job" and i + 1 < len(args):
          job_filter = args[i + 1]
          break
  if job_filter:
      params["job"] = job_filter
  ```
- [ ] In `telec.py`, update `sessions list` CommandDef flags (line 182) to include
  `Flag("--job", desc="Filter by session_metadata.job value")`
- [ ] Write tests in `tests/unit/test_session_list_job_filter.py`:
  - `test_list_sessions_job_filter_matches` — API returns only sessions with matching job
  - `test_list_sessions_job_filter_no_match` — returns empty when no sessions match
  - `test_list_sessions_no_job_filter` — returns all when filter absent
  - `test_sessions_list_cli_job_flag` — CLI sends correct `job` param

**Why:** The spawn guard needs a reliable way to query for active integrator sessions.
A server-side filter on the existing listing surface composes with all existing
visibility rules (initiator scoping, `--all`, `--closed`, role-based visibility).

**Verification:** New tests pass; existing list tests remain green.

---

### Task 6: Update CLI `CommandAuth` entries for integrator role (selective, not `_SYS_ALL`)

**File(s):** `teleclaude/cli/telec.py`, `tests/unit/test_command_auth.py`

- [ ] Import `ROLE_INTEGRATOR` from constants
- [ ] Add `_SYS_INTG = frozenset({ROLE_INTEGRATOR})`
- [ ] **Do NOT widen `_SYS_ALL`** — leave it as `frozenset({ROLE_WORKER, ROLE_ORCHESTRATOR})`
- [ ] Selectively update only the CommandAuth entries that correspond to tools in
  `INTEGRATOR_ALLOWED_TOOLS`:

  | CLI command path  | Current auth `system=` | New auth `system=`      |
  |-------------------|------------------------|-------------------------|
  | `sessions list`   | `_SYS_ALL`             | `_SYS_ALL \| _SYS_INTG` |
  | `sessions tail`   | `_SYS_ALL`             | `_SYS_ALL \| _SYS_INTG` |
  | `sessions result` | `_SYS_ALL`             | `_SYS_ALL \| _SYS_INTG` |
  | `sessions escalate` | `_SYS_ALL`           | `_SYS_ALL \| _SYS_INTG` |
  | `operations get`  | `_SYS_ALL`             | `_SYS_ALL \| _SYS_INTG` |
  | `todo integrate`  | `_SYS_ORCH`            | `_SYS_ORCH \| _SYS_INTG` |

- [ ] All other `_SYS_ALL` commands remain unchanged — integrator is NOT added to them.
  This means `sessions send`, `sessions file`, `sessions widget`, `channels list`,
  `channels publish`, etc. are all CLI-blocked for integrator, matching the whitelist.
- [ ] Write tests in `tests/unit/test_command_auth.py`:
  - `test_integrator_allowed_todo_integrate`
  - `test_integrator_blocked_todo_work`
  - `test_integrator_blocked_sessions_send`
  - `test_integrator_allowed_sessions_list`
  - `test_integrator_allowed_sessions_tail`
  - `test_integrator_cli_auth_mirrors_whitelist` — for every tool in
    `INTEGRATOR_ALLOWED_TOOLS`, assert the corresponding CommandAuth includes
    `ROLE_INTEGRATOR`; for every `_SYS_ALL` command NOT in the whitelist, assert it
    does NOT include `ROLE_INTEGRATOR`

**Why:** The plan review (round 1, finding #1) identified that widening `_SYS_ALL`
would over-authorize integrator sessions for commands like `sessions send`,
`channels publish`, and `todo validate` — commands not in the integrator whitelist.
Selective updates keep CLI auth aligned with the runtime permission model. The
mirror test encodes this invariant so future CommandAuth changes cannot silently
break alignment.

**Verification:** New tests pass; existing CommandAuth completeness test passes.

---

### Task 7: Switch integrator bridge to `sessions run` and replace spawn guard

**File(s):** `teleclaude/core/integration_bridge.py`,
`tests/unit/test_integration_bridge_spawn.py`

- [ ] Replace the spawn guard (lines 284-296) with structured `--job` query:
  ```python
  list_result = subprocess.run(
      ["telec", "sessions", "list", "--all", "--job", "integrator"],
      capture_output=True, text=True, timeout=10,
  )
  if list_result.returncode == 0:
      sessions = json.loads(list_result.stdout)
      if sessions:
          logger.info("Integrator session already running; candidate %s queued for drain", slug)
          return None
  ```
- [ ] Replace `telec sessions start` spawn (lines 303-315) with `telec sessions run`:
  ```python
  start_result = subprocess.run(
      ["telec", "sessions", "run",
       "--command", "/next-integrate",
       "--project", project_path,
       "--detach"],
      env=spawn_env,
      capture_output=True, text=True, timeout=30,
  )
  ```
  Remove `--message`, `--title` flags.
- [ ] Add `import json` if not already imported
- [ ] Write tests in `tests/unit/test_integration_bridge_spawn.py`:
  - `test_spawn_guard_uses_job_filter` — mock `subprocess.run` returning sessions JSON,
    function returns None
  - `test_spawn_guard_empty_allows_spawn` — mock returns `[]`, spawn proceeds
  - `test_spawn_uses_sessions_run` — verify command includes
    `["telec", "sessions", "run", "--command", "/next-integrate", ...]`
  - `test_spawn_guard_list_failure_continues` — when list command fails (non-zero exit
    or timeout), spawn proceeds rather than blocking

**Why:** Routing through `sessions run` means the server derives metadata from the
command name. The structured `--job` query replaces the fragile string match, so dead
sessions without metadata don't falsely block spawning.

**Verification:** New tests pass; existing integration bridge tests remain green.

---

### Task 8: Full suite verification

**File(s):** (none — verification only)

- [ ] Run `make test` — all tests pass
- [ ] Run `make lint` — no violations
- [ ] Pre-commit hooks pass on committed changes

**Why:** Integration across 8+ files creates risk of subtle breakage. The full suite
is the safety net.

**Verification:** Clean exit from `make test` and `make lint`.

## Referenced paths

- `teleclaude/constants.py`
- `teleclaude/core/tool_access.py`
- `teleclaude/api/auth.py`
- `teleclaude/api_server.py`
- `teleclaude/api_models.py`
- `teleclaude/cli/tool_commands.py`
- `teleclaude/cli/telec.py`
- `teleclaude/core/integration_bridge.py`
- `teleclaude/core/models.py`
- `tests/unit/test_role_tools.py`
- `tests/unit/test_command_auth.py`
- `tests/unit/test_api_auth.py`
- `tests/unit/test_run_session_metadata.py`
- `tests/unit/test_session_list_job_filter.py`
- `tests/unit/test_integration_bridge_spawn.py`

## Deferred

None. All requirements are addressed within this plan.
