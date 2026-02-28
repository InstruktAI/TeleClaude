# Implementation Plan: cli-cleanup-maintain-cwd-delivered

## Overview

Three independent cleanup items in one pass. Order: remove maintain first (reduces noise), fix cwd defaults, then add delivered flags.

## Phase 1: Remove `telec todo maintain`

### Task 1.1: Remove state machine and imports

**File(s):** `teleclaude/core/next_machine/maintain.py`, `teleclaude/core/next_machine/__init__.py`

- [ ] Delete `maintain.py`
- [ ] Remove `next_maintain` import from `__init__.py`

### Task 1.2: Remove API route and clearance

**File(s):** `teleclaude/api/todo_routes.py`, `teleclaude/api/auth.py`

- [ ] Remove `/maintain` endpoint and `next_maintain` import from `todo_routes.py`
- [ ] Remove `CLEARANCE_TODOS_MAINTAIN` from `auth.py`

### Task 1.3: Remove CLI command

**File(s):** `teleclaude/cli/tool_commands.py`, `teleclaude/cli/telec.py`

- [ ] Remove `handle_todo_maintain` function from `tool_commands.py`
- [ ] Remove import of `handle_todo_maintain` in `telec.py`
- [ ] Remove `"maintain"` entry from `CLI_SURFACE` dict in `telec.py`
- [ ] Remove `elif subcommand == "maintain"` dispatch in `telec.py`

### Task 1.4: Remove access control and mappings

**File(s):** `teleclaude/core/tool_access.py`, `teleclaude/core/tool_activity.py`, `scripts/diagrams/extract_commands.py`

- [ ] Remove `"telec todo maintain"` from `UNAUTHORIZED_EXCLUDED_TOOLS`
- [ ] Remove `"next_maintain"` from activity mapping
- [ ] Remove `"next-maintain"` from diagram extraction

---

## Phase 2: Remove `--cwd` / `--project-root` from CLI surface

### Task 2.1: Remove flag definitions from CLI_SURFACE

**File(s):** `teleclaude/cli/telec.py`

- [ ] Delete `_PROJECT_ROOT` and `_PROJECT_ROOT_LONG` flag definitions (lines 130-131)
- [ ] Remove all `_PROJECT_ROOT` / `_PROJECT_ROOT_LONG` references from CLI_SURFACE entries (~15 locations across todo, roadmap, bugs, docs subcommands)
- [ ] Remove all `Flag("--cwd", ...)` entries from CLI_SURFACE

### Task 2.2: Remove `--project-root` parsing from telec.py handlers

**File(s):** `teleclaude/cli/telec.py`

- [ ] In every handler that parses `--project-root` (~26 locations), remove the arg parsing branch and set `project_root = Path.cwd()` unconditionally
- [ ] Affected handlers: `_handle_todo_create`, `_handle_todo_remove`, `_handle_todo_validate`, `_handle_todo_demo`, `_handle_roadmap_show`, `_handle_roadmap_add`, `_handle_roadmap_remove`, `_handle_roadmap_move`, `_handle_roadmap_deps`, `_handle_roadmap_freeze`, `_handle_roadmap_deliver`, `_handle_bugs_create`, `_handle_bugs_report`, `_handle_bugs_list`, and any others

### Task 2.3: Remove `--cwd` parsing from tool_commands.py handlers

**File(s):** `teleclaude/cli/tool_commands.py`

- [ ] In `handle_todo_prepare`: remove `--cwd` arg parsing, set `body["cwd"] = os.getcwd()` unconditionally
- [ ] In `handle_todo_mark_phase`: remove `--cwd` arg parsing and required check, set `body["cwd"] = os.getcwd()` unconditionally
- [ ] In `handle_todo_set_deps`: remove `--cwd` arg parsing and required check, set `cwd = os.getcwd()` unconditionally
- [ ] Update docstrings/help text to remove `--cwd` references

---

## Phase 3: Add `--include-delivered` / `--delivered-only` to roadmap list

### Task 3.1: Reuse existing `load_delivered`

**File(s):** No changes needed — `load_delivered(cwd: str) -> list[DeliveredEntry]` already exists at `teleclaude/core/next_machine/core.py:1340` and returns full records (slug, date, title, commit, description, children) from `delivered.yaml`. `DeliveredEntry` dataclass is at line 1313.

- [x] Confirmed: function exists and returns the needed data. No new code required.

### Task 3.2: Extend `assemble_roadmap`

**File(s):** `teleclaude/core/roadmap.py`

- [ ] Add `include_delivered: bool = False` and `delivered_only: bool = False` parameters to `assemble_roadmap`
- [ ] Mirror the icebox pattern: when `delivered_only`, set `include_delivered = True`
- [ ] Import `load_delivered` from `teleclaude.core.next_machine.core`
- [ ] After icebox loading (step 2), add step 2b: when `include_delivered`, iterate `load_delivered()` entries and call `append_todo(slug, description=entry.description or entry.title, group="Delivered")`
- [ ] When `delivered_only`, skip active roadmap loading (same as `icebox_only` skips active items)
- [ ] Set `status="delivered"` on the resulting `TodoInfo` entries

### Task 3.3: Add flags to CLI

**File(s):** `teleclaude/cli/telec.py`

- [ ] Add `Flag("--include-delivered", "-d", "Include delivered items")` and `Flag("--delivered-only", desc="Show only delivered items")` to `roadmap list` in CLI_SURFACE
- [ ] Parse both flags in `_handle_roadmap_show` (mirror the `--include-icebox`/`--icebox-only` arg parsing pattern)
- [ ] Pass `include_delivered` and `delivered_only` to `assemble_roadmap`

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Run `make test` — all existing tests pass
- [ ] Verify `telec todo mark-phase` and `telec todo set-deps` work without `--cwd`
- [ ] Verify `telec roadmap list --include-delivered` and `--delivered-only` produce correct output

### Task 4.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
