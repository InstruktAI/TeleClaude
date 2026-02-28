# Implementation Plan: cli-cleanup-maintain-cwd-delivered

## Overview

Three independent cleanup items in one pass. Order: remove maintain first (reduces noise), fix cwd defaults, then add delivered flags.

## Phase 1: Remove `telec todo maintain`

### Task 1.1: Remove state machine and imports

**File(s):** `teleclaude/core/next_machine/maintain.py`, `teleclaude/core/next_machine/__init__.py`

- [x] Delete `maintain.py`
- [x] Remove `next_maintain` import from `__init__.py`

### Task 1.2: Remove API route and clearance

**File(s):** `teleclaude/api/todo_routes.py`, `teleclaude/api/auth.py`

- [x] Remove `/maintain` endpoint and `next_maintain` import from `todo_routes.py`
- [x] Remove `CLEARANCE_TODOS_MAINTAIN` from `auth.py`

### Task 1.3: Remove CLI command

**File(s):** `teleclaude/cli/tool_commands.py`, `teleclaude/cli/telec.py`

- [x] Remove `handle_todo_maintain` function from `tool_commands.py`
- [x] Remove import of `handle_todo_maintain` in `telec.py`
- [x] Remove `"maintain"` entry from `CLI_SURFACE` dict in `telec.py`
- [x] Remove `elif subcommand == "maintain"` dispatch in `telec.py`

### Task 1.4: Remove access control and mappings

**File(s):** `teleclaude/core/tool_access.py`, `teleclaude/core/tool_activity.py`, `scripts/diagrams/extract_commands.py`

- [x] Remove `"telec todo maintain"` from `UNAUTHORIZED_EXCLUDED_TOOLS`
- [x] Remove `"next_maintain"` from activity mapping
- [x] Remove `"next-maintain"` from diagram extraction

---

## Phase 2: Remove `--cwd` / `--project-root` from CLI surface

### Task 2.1: Remove flag definitions from CLI_SURFACE

**File(s):** `teleclaude/cli/telec.py`

- [x] Delete `_PROJECT_ROOT` and `_PROJECT_ROOT_LONG` flag definitions (lines 130-131)
- [x] Remove all `_PROJECT_ROOT` / `_PROJECT_ROOT_LONG` references from CLI_SURFACE entries (~15 locations across todo, roadmap, bugs, docs subcommands)
- [x] Remove all `Flag("--cwd", ...)` entries from CLI_SURFACE

### Task 2.2: Remove `--project-root` parsing from telec.py handlers

**File(s):** `teleclaude/cli/telec.py`

In each handler below, remove the `--project-root` arg parsing branch. The `project_root = Path.cwd()` line stays — it just becomes unconditional.

- [x] `_handle_sync` (line ~1427)
- [x] `_handle_watch` (line ~1451)
- [x] `_handle_docs_index` (line ~1529) — also remove the missing-value error branch
- [x] `_handle_docs_get` (line ~1586) — also remove the missing-value error branch
- [x] `_handle_todo_validate` (line ~1662)
- [x] `_handle_todo_demo` (line ~2016)
- [x] `_handle_todo_create` (line ~2066)
- [x] `_handle_todo_remove` (line ~2114)
- [x] `_handle_roadmap_show` (line ~2186)
- [x] `_handle_roadmap_add` (line ~2284)
- [x] `_handle_roadmap_remove` (line ~2336)
- [x] `_handle_roadmap_move` (line ~2378)
- [x] `_handle_roadmap_deps` (line ~2432)
- [x] `_handle_roadmap_freeze` (line ~2492)
- [x] `_handle_roadmap_deliver` (line ~2533)
- [x] `_handle_bugs_create` (line ~2596) — also remove from usage strings
- [x] `_handle_bugs_report` (line ~2647)
- [x] `_handle_bugs_list` (line ~2776)
- [x] Update docstrings that mention `--project-root` in handler docstrings

### Task 2.3: Remove `--project-root` from config_cmd.py handlers

**File(s):** `teleclaude/cli/config_cmd.py`

- [x] `handle_get` (line ~111): remove `--project-root` parsing, use `Path.cwd()`
- [x] `handle_patch` (line ~168): same
- [x] `handle_validate` (line ~239): same

### Task 2.4: Remove `--cwd` parsing from tool_commands.py handlers

**File(s):** `teleclaude/cli/tool_commands.py`

- [x] In `handle_todo_prepare`: remove `--cwd` arg parsing, set `body["cwd"] = os.getcwd()` unconditionally
- [x] In `handle_todo_mark_phase`: remove `--cwd` arg parsing and required check, set `body["cwd"] = os.getcwd()` unconditionally
- [x] In `handle_todo_set_deps`: remove `--cwd` arg parsing and required check, set `cwd = os.getcwd()` unconditionally
- [x] Update docstrings/help text to remove `--cwd` references

### Task 2.5: Fix internal subprocess callers

**File(s):** `teleclaude/cli/watch.py`, `teleclaude/core/next_machine/core.py`

These shell out to `telec` with `--project-root`. Both already pass `cwd=` to `subprocess.run`, so removing the flag from the command list is safe — the subprocess inherits cwd.

- [x] `teleclaude/cli/watch.py:144` — remove `"--project-root", str(self.project_root)` from the command list
- [x] `teleclaude/core/next_machine/core.py:425` — remove `"--project-root", worktree_cwd` from the command list

### Task 2.6: Fix tests to use monkeypatch.chdir

**File(s):** `tests/integration/test_telec_cli_commands.py`, `tests/unit/test_telec_cli.py`, `tests/unit/test_next_machine_demo.py`, `tests/unit/test_bugs_list_status_parity.py`

Tests are the only consumer of `--project-root`. Replace with `monkeypatch.chdir(tmp_path)` so they exercise the real code path.

- [x] `tests/integration/test_telec_cli_commands.py` — 4 occurrences (lines ~47, ~86, ~126, ~146)
- [x] `tests/unit/test_telec_cli.py` — 3 occurrences (lines ~307, ~332, ~336)
- [x] `tests/unit/test_next_machine_demo.py` — 1 occurrence (line ~514)
- [x] `tests/unit/test_bugs_list_status_parity.py` — 2 occurrences (lines ~28, ~32)

### NOT in scope (standalone scripts with own argparse, not `telec` commands)

- `scripts/distribute.py` — called from `sync.py` which passes path explicitly
- `teleclaude/entrypoints/macos_setup.py` — standalone macOS init entrypoint
- `tools/migrations/migrate_requires.py` — one-off migration script

---

## Phase 3: Add `--include-delivered` / `--delivered-only` to roadmap list

### Task 3.1: Reuse existing `load_delivered`

**File(s):** No changes needed — `load_delivered(cwd: str) -> list[DeliveredEntry]` already exists at `teleclaude/core/next_machine/core.py:1340` and returns full records (slug, date, title, commit, description, children) from `delivered.yaml`. `DeliveredEntry` dataclass is at line 1313.

- [x] Confirmed: function exists and returns the needed data. No new code required.

### Task 3.2: Add `delivered_at` to `TodoInfo`

**File(s):** `teleclaude/core/models.py`

`TodoInfo` represents the full lifecycle of a work item. Delivered is a lifecycle state, and the date belongs on the model — not just in `DeliveredEntry`.

- [x] Add `delivered_at: Optional[str] = None` to the `TodoInfo` dataclass (date string, e.g. `"2026-02-27"`)

### Task 3.3: Extend `assemble_roadmap`

**File(s):** `teleclaude/core/roadmap.py`

- [x] Add `include_delivered: bool = False` and `delivered_only: bool = False` parameters to `assemble_roadmap`
- [x] Mirror the icebox pattern: when `delivered_only`, set `include_delivered = True`
- [x] Import `load_delivered` from `teleclaude.core.next_machine.core`
- [x] After icebox loading (step 2), add step 2b: when `include_delivered`, iterate `load_delivered()` entries, call `append_todo(slug, description=entry.description or entry.title, group="Delivered")`, then set `delivered_at=entry.date` on the resulting `TodoInfo`
- [x] When `delivered_only`, skip active roadmap loading (same as `icebox_only` skips active items)
- [x] Set `status="delivered"` on the resulting `TodoInfo` entries

### Task 3.4: Add flags to CLI and render `delivered_at`

**File(s):** `teleclaude/cli/telec.py`

- [x] Add `Flag("--include-delivered", "-d", "Include delivered items")` and `Flag("--delivered-only", desc="Show only delivered items")` to `roadmap list` in CLI_SURFACE
- [x] Parse both flags in `_handle_roadmap_show` (mirror the `--include-icebox`/`--icebox-only` arg parsing pattern)
- [x] Pass `include_delivered` and `delivered_only` to `assemble_roadmap`
- [x] In the renderer, include `delivered_at` in the extras when set: e.g. `Delivered:2026-02-27`

---

## Phase 4: Validation

### Task 4.1: Tests

- [x] Run `make test` — all existing tests pass (including refactored test files)
- [x] Verify no CLI command accepts `--project-root` or `--cwd`
- [x] Verify `telec roadmap list --include-delivered` and `--delivered-only` produce correct output

### Task 4.2: Quality Checks

- [x] Run `make lint`
- [x] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
