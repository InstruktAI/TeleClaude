# Implementation Plan: rlf-cli

## Overview

Convert two monolithic CLI files into Python packages by extracting handler groups and shared infrastructure into smaller submodules. Both old files become `__init__.py` thin wrappers that re-export all symbols for backward-compatible imports.

**`telec.py` → `telec/` package structure:**
- `__init__.py` — core dispatch, TUI, `main()`, re-exports (~250 lines)
- `surface.py` — `CommandAuth`, `Flag`, `CommandDef`, `TelecCommand`, `CLI_SURFACE` (~800 lines)
- `auth.py` — `_resolve_command_auth`, `is_command_allowed` (~80 lines)
- `help.py` — all usage/completion functions (~450 lines)
- `handlers/__init__.py` — empty
- `handlers/misc.py` — version, sync, watch, revive, tmux, computers, projects (~280 lines)
- `handlers/docs.py` — docs handlers (~160 lines)
- `handlers/demo.py` — demo helper functions + `_handle_todo_demo` (~380 lines)
- `handlers/todo.py` — remaining todo handlers (~340 lines)
- `handlers/roadmap.py` — roadmap handlers (~500 lines)
- `handlers/bugs.py` — bugs handlers (~220 lines)
- `handlers/config.py` — config handler (~40 lines)
- `handlers/content.py` — content handlers (~100 lines)
- `handlers/events_signals.py` — events + signals handlers (~100 lines)
- `handlers/auth_cmds.py` — auth/login/whoami/logout handlers (~155 lines)
- `handlers/history.py` — history handlers (~155 lines)
- `handlers/memories.py` — memories handlers (~340 lines)

**`tool_commands.py` → `tool_commands/` package structure:**
- `__init__.py` — re-exports only (~30 lines)
- `sessions.py` — sessions handlers (~715 lines)
- `todo.py` — todo+operations handlers (~410 lines)
- `infra.py` — computers, projects, agents, channels (~300 lines)

---

## Phase 1: Create `telec/` package

### Task 1.1: Extract surface module

**File(s):** `teleclaude/cli/telec/surface.py`

- [x] Create `teleclaude/cli/telec/` directory
- [x] Extract `TelecCommand` enum, `CommandAuth`, `Flag`, `CommandDef`, auth shorthand constants, and `CLI_SURFACE` dict to `surface.py`
- [x] Add necessary imports to `surface.py`

### Task 1.2: Extract auth module

**File(s):** `teleclaude/cli/telec/auth.py`

- [x] Extract `_resolve_command_auth` and `is_command_allowed` to `auth.py`
- [x] Import `CLI_SURFACE`, `CommandAuth` from `surface.py` within `auth.py`

### Task 1.3: Extract help module

**File(s):** `teleclaude/cli/telec/help.py`

- [x] Extract all `_usage*`, `_print_completion`, `_handle_completion`, completion helpers to `help.py`
- [x] Import `CLI_SURFACE`, `CommandDef`, `Flag` from `surface.py`

### Task 1.4: Extract handlers/misc module

**File(s):** `teleclaude/cli/telec/handlers/misc.py`

- [x] Create `teleclaude/cli/telec/handlers/` directory with empty `__init__.py`
- [x] Extract `_handle_version`, `_git_short_commit_hash`, `_handle_sync`, `_handle_watch`, `_handle_revive`, `_revive_session`, `_revive_session_via_api`, `_send_revive_enter_via_api`, `_attach_tmux_session`, `_handle_computers`, `_handle_projects`, tmux helpers to `handlers/misc.py`

### Task 1.5: Extract handlers/docs module

**File(s):** `teleclaude/cli/telec/handlers/docs.py`

- [x] Extract `_handle_docs`, `_handle_docs_index`, `_handle_docs_get` to `handlers/docs.py`

### Task 1.6: Extract handlers/demo and handlers/todo modules

**File(s):** `teleclaude/cli/telec/handlers/demo.py`, `teleclaude/cli/telec/handlers/todo.py`

- [x] Extract demo helper functions (`_extract_demo_blocks`, `_find_demo_md`, `_check_no_demo_marker`, `_demo_list`, `_demo_validate`, `_demo_run`, `_demo_create`) and `_handle_todo_demo` to `handlers/demo.py`
- [x] Extract remaining todo handlers (`_handle_todo`, `_handle_todo_validate`, `_handle_todo_verify_artifacts`, `_handle_todo_dump`, `_handle_todo_split`, `_handle_todo_create`, `_handle_todo_remove`) to `handlers/todo.py`

### Task 1.7: Extract handlers/roadmap module

**File(s):** `teleclaude/cli/telec/handlers/roadmap.py`

- [x] Extract all `_handle_roadmap*` functions to `handlers/roadmap.py`

### Task 1.8: Extract handlers/bugs module

**File(s):** `teleclaude/cli/telec/handlers/bugs.py`

- [x] Extract all `_handle_bugs*` functions to `handlers/bugs.py`

### Task 1.9: Extract small handler modules

**File(s):** `handlers/config.py`, `handlers/content.py`, `handlers/events_signals.py`, `handlers/auth_cmds.py`, `handlers/history.py`, `handlers/memories.py`

- [x] Extract `_handle_config` to `handlers/config.py`
- [x] Extract `_handle_content`, `_handle_content_dump` to `handlers/content.py`
- [x] Extract `_handle_events`, `_handle_events_list`, `_handle_signals`, `_handle_signals_status` to `handlers/events_signals.py`
- [x] Extract `_handle_auth`, `_role_for_email`, `_requires_tui_login`, `_handle_login`, `_handle_whoami`, `_handle_logout` to `handlers/auth_cmds.py`
- [x] Extract `_handle_history`, `_handle_history_search`, `_handle_history_show` to `handlers/history.py`
- [x] Extract all `_handle_memories*` to `handlers/memories.py`

### Task 1.10: Create `telec/__init__.py`

**File(s):** `teleclaude/cli/telec/__init__.py`, remove `teleclaude/cli/telec.py`

- [x] Create `__init__.py` with module-level imports, `_ConfigProxy`, `main()`, `_run_tui`, `_run_tui_config_mode`, `_handle_cli_command`, and re-exports of all public symbols
- [x] Remove old `teleclaude/cli/telec.py`
- [x] Update `pyproject.toml` lint exceptions: replace `teleclaude/cli/telec.py` with `teleclaude/cli/telec/**`

---

## Phase 2: Create `tool_commands/` package

### Task 2.1: Extract tool_commands/sessions module

**File(s):** `teleclaude/cli/tool_commands/sessions.py`

- [x] Extract all `handle_sessions*` and `_sessions_help` to `sessions.py`

### Task 2.2: Extract tool_commands/todo module

**File(s):** `teleclaude/cli/tool_commands/todo.py`

- [x] Extract `handle_todo_create`, `handle_todo_prepare`, `handle_todo_work`, `handle_todo_integrate`, `handle_operations`, `_operations_help`, `handle_operations_get`, `_print_operation_recovery`, `handle_todo_mark_phase`, `handle_todo_mark_finalize_ready`, `handle_todo_set_deps` to `todo.py`

### Task 2.3: Extract tool_commands/infra module and create __init__.py

**File(s):** `teleclaude/cli/tool_commands/infra.py`, `teleclaude/cli/tool_commands/__init__.py`, remove `teleclaude/cli/tool_commands.py`

- [x] Extract `handle_computers`, `handle_projects`, `handle_agents`, `handle_agents_availability`, `handle_agents_status`, `handle_channels`, `handle_channels_list`, `handle_channels_publish` to `infra.py`
- [x] Create `__init__.py` that re-exports all public symbols from `sessions`, `todo`, `infra`
- [x] Update `tool_commands/sessions.py` lazy import of `_handle_revive` from new location
- [x] Remove old `teleclaude/cli/tool_commands.py`

---

## Phase 3: Validation

### Task 3.1: Tests

- [x] Run `make test` — 139 passed

### Task 3.2: Quality Checks

- [x] Run `make lint` — ruff/pyright/mypy/pylint all pass on new modules; guardrails fails on 19 pre-existing violations outside this task's scope (was 21 before, reduced by removing telec.py and tool_commands.py)
- [x] Verify no unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable) — none needed
