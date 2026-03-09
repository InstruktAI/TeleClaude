# Implementation Plan: session-role-metadata

## Overview

Introduce `integrator` as a first-class session permission profile, add structured `job`
metadata to command-driven session creation, replace the integrator spawn guard's
title-text heuristic with a structured metadata query, and unify daemon authorization
onto the CLI's `CommandAuth` dual-factor model.

The change flows through one chain: constant definition -> CLI CommandAuth alignment ->
daemon auth wiring (`is_command_allowed` replaces legacy `is_tool_allowed`) ->
auth derivation -> server-side metadata injection -> session listing filter -> spawn
guard replacement.

**Execution order note:** Task 6 (CommandAuth entries) must complete before Task 2
(daemon auth wiring), since `is_command_allowed` reads from `CLI_SURFACE`.

## Tasks

### Task 1: Add `ROLE_INTEGRATOR` constant

**File(s):** `teleclaude/constants.py`

- [ ] Add `ROLE_INTEGRATOR = "integrator"` after existing `ROLE_WORKER` (line 39)

**Why:** Every downstream component references role constants. A shared constant
prevents string literals from drifting.

**Verification:** Import succeeds; existing tests still pass.

---

### Task 2: Wire `is_command_allowed()` into daemon auth, retire legacy `is_tool_allowed()`

**File(s):** `teleclaude/api/auth.py`, `teleclaude/core/tool_access.py`,
`tests/unit/test_role_tools.py`, `tests/unit/test_api_auth.py`,
`tests/unit/test_help_desk_features.py`

**Depends on:** Task 6 (CommandAuth entries must include integrator before wiring)

- [ ] In `_is_tool_denied()` in `auth.py`, replace the call to `is_tool_allowed()` with
  `is_command_allowed()` from `telec.py`:
  ```python
  from teleclaude.cli.telec import is_command_allowed

  def _is_tool_denied(tool_name: str, identity: CallerIdentity) -> bool:
      return not is_command_allowed(tool_name, identity.system_role, identity.human_role)
  ```
- [ ] If circular import arises, extract `is_command_allowed`, `_resolve_command_auth`,
  and `CommandAuth` to `teleclaude/core/command_auth.py` and import from there in both
  `telec.py` and `auth.py`
- [ ] Remove from `tool_access.py`: `is_tool_allowed()`, `WORKER_ALLOWED_TOOLS`,
  `UNAUTHORIZED_EXCLUDED_TOOLS`, `MEMBER_EXCLUDED_TOOLS`, `_get_human_excluded_tools()`
- [ ] Keep `tool_access.py` if other exported symbols remain; remove if fully empty
- [ ] Rebuild `get_excluded_tools()` / `filter_tool_names()` from `CLI_SURFACE`
  human-role auth so help-desk/customer filtering keeps its current behavior without
  the retired hardcoded exclusion sets
- [ ] Update/replace tests in `tests/unit/test_role_tools.py`:
  - Remove tests for legacy exclusion sets
  - Add `test_command_auth_worker_restricted` — worker blocked from orchestrator-only commands
  - Add `test_command_auth_integrator_restricted` — integrator blocked from non-whitelist commands
- [ ] Add tests in `tests/unit/test_api_auth.py`:
  - `test_tool_denied_uses_command_auth` — orchestrator with valid human_role allowed
    for `sessions end`
  - `test_tool_denied_null_human_role_fails_closed` — any system_role with null
    human_role → denied
  - `test_tool_denied_worker_restricted` — worker blocked from orchestrator-only commands
  - `test_tool_denied_integrator_restricted` — integrator blocked from non-whitelist commands
- [ ] Keep/update tests in `tests/unit/test_help_desk_features.py` so customer/member
  exclusion behavior stays covered after the `tool_access.py` refactor

**Why:** The legacy `is_tool_allowed()` uses hardcoded exclusion sets that don't
properly handle system roles beyond worker. `is_command_allowed()` uses the CommandAuth
declarations in `CLI_SURFACE` — the same source of truth the CLI uses — providing
dual-factor (system_role + human_role) authorization. Single source of truth eliminates
drift between CLI and daemon auth. This directly fixes the bug where orchestrator
sessions with null human_role were denied with "role 'unauthorized'" because the legacy
code collapsed system_role and human_role checks into one path.

**Verification:** New tests pass; auth, role, and help-desk filtering tests pass or are updated.

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
  - `test_list_sessions_job_filter_respects_initiator_scope_without_all` — job filter
    narrows the default initiator-scoped view instead of bypassing it
  - `test_list_sessions_job_filter_respects_role_visibility` — web/member visibility
    rules still apply before job filtering
  - `test_list_sessions_job_filter_respects_closed_flag` — closed sessions stay excluded
    unless `--closed` is requested
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

### Task 8: Update the demo artifact to match the approved architecture

**File(s):** `todos/session-role-metadata/demo.md`

- [ ] Replace legacy `tool_access.py` validation blocks with checks that reflect the
  approved architecture:
  - `is_command_allowed()` / daemon auth behavior for integrator access
  - `COMMAND_ROLE_MAP` metadata derivation
  - `telec sessions list --help` documenting `--job`
  - integrator spawn using `telec sessions run --command /next-integrate`
- [ ] Update the guided presentation text so it describes CommandAuth as the daemon
  source of truth and removes references to widening `_SYS_ALL` or
  `sessions start --title integrator`

**Why:** Review always checks `demo.md`. The current demo still describes the superseded
`tool_access.py` path, so it must be brought in line with the approved plan before build.

**Verification:** `telec todo demo validate session-role-metadata` passes, or any
remaining validation gap is explicit and reviewable.

---

### Task 9: Verification with targeted tests plus normal hook path

**File(s):** (none — verification only)

- [ ] Run targeted tests for the touched surfaces:
  - `tests/unit/test_command_auth.py`
  - `tests/unit/test_api_auth.py`
  - `tests/unit/test_role_tools.py`
  - `tests/unit/test_help_desk_features.py`
  - `tests/unit/test_run_session_metadata.py`
  - `tests/unit/test_session_list_job_filter.py`
  - `tests/unit/test_integration_bridge_spawn.py`
- [ ] Run the repo's normal pre-commit verification path before commit
- [ ] Escalate to broader test scope only if the targeted tests or hooks expose wider
  regressions; do not default to `make test`
- [ ] Run `make lint` only if the hook output leaves lint/type status ambiguous or the
  hook path does not cover it

**Why:** This satisfies the success criteria while matching repository policy:
targeted tests during development, then the normal hook path as the final gate.

**Verification:** Targeted tests pass and the normal pre-commit verification path is green.

## Referenced paths

- `teleclaude/constants.py`
- `teleclaude/core/tool_access.py`
- `teleclaude/core/command_auth.py`
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
- `tests/unit/test_help_desk_features.py`
- `tests/unit/test_run_session_metadata.py`
- `tests/unit/test_session_list_job_filter.py`
- `tests/unit/test_integration_bridge_spawn.py`
- `todos/session-role-metadata/demo.md`

## Deferred

None. All requirements are addressed within this plan.
