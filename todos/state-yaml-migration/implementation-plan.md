# Implementation Plan: state-yaml-migration

## Overview

Pure serialization format migration: replace `json.loads`/`json.dumps` with `yaml.safe_load`/`yaml.dump` for todo state files. The approach is surgical — change the read/write functions at the core, update references, migrate existing files, and add a backward-compat fallback for the transition period.

All changes are confined to serialization plumbing. No Pydantic model changes, no behavioral changes.

## Phase 1: Core Read/Write Migration

### Task 1.1: Update core state functions

**File(s):** `teleclaude/core/next_machine/core.py`

- [x] Change `get_state_path()` to return `state.yaml` instead of `state.json`
- [x] Update `read_phase_state()`:
  - Try `state.yaml` first
  - Fall back to `state.json` if `state.yaml` doesn't exist (backward compat)
  - Replace `json.loads()` with `yaml.safe_load()`
- [x] Update `write_phase_state()`:
  - Replace `json.dumps()` with `yaml.dump()` (use `default_flow_style=False, sort_keys=False`)
  - Write to `state.yaml`
- [x] Update `sweep_completed_groups()` which reads `state.json` directly via `json.loads` — change to use `read_phase_state()` or replicate the YAML fallback
- [x] Update the `DEFAULT_STATE` comment and `roadmap.yaml` header reference from `state.json` to `state.yaml`
- [x] Update `POST_COMPLETION` dict strings that mention `state.json`
- [x] Update all other comments/docstrings in `core.py` referencing `state.json` (~15 occurrences)

### Task 1.2: Update scaffold

**File(s):** `teleclaude/todo_scaffold.py`

- [x] Change `state.json` filename to `state.yaml` in `create_todo_skeleton()`
- [x] Replace `json.dumps(_DEFAULT_STATE)` with `yaml.dump(_DEFAULT_STATE)` for initial state content
- [x] Add `import yaml` (already available as project dependency)

### Task 1.3: Update validation

**File(s):** `teleclaude/resource_validation.py`

- [x] Update `validate_todo()` to check for `state.yaml` (with fallback to `state.json`)
- [x] Update error messages from `state.json` to `state.yaml`

### Task 1.4: Update roadmap assembly

**File(s):** `teleclaude/core/roadmap.py`

- [x] Update direct `state.json` reads to `state.yaml` (with fallback)
- [x] Replace `json.loads` with `yaml.safe_load`

### Task 1.5: Update worktree sync file lists

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Update `sync_slug_todo_from_worktree_to_main()` file list: `state.json` → `state.yaml`
- [ ] Update `sync_slug_todo_from_main_to_worktree()` file list: `state.json` → `state.yaml`

### Task 1.6: Update todo watcher

**File(s):** `teleclaude/core/todo_watcher.py`

- [ ] Update docstring/comments referencing `state.json`
- [ ] Update any file-matching patterns if the watcher filters by filename

### Task 1.7: Update MCP tool descriptions and CLI help

**File(s):** `teleclaude/mcp/tool_definitions.py`, `teleclaude/mcp/handlers.py`, `teleclaude/cli/telec.py`

- [ ] Update `next_work` tool description (`tool_definitions.py:721`)
- [ ] Update `mark_phase` tool description (`tool_definitions.py:747-748`)
- [ ] Update `mark_phase` handler docstring (`handlers.py:1115`)
- [ ] Update CLI `todo validate` description (`telec.py:156`)

---

## Phase 2: Migrate Existing Files

### Task 2.1: Write migration logic

**File(s):** `teleclaude/todo_scaffold.py` (or inline script)

- [ ] For each `todos/*/state.json`:
  1. Read JSON content
  2. Parse with `json.loads`
  3. Write as YAML to `state.yaml` in the same directory
  4. Remove `state.json`
- [ ] Handle edge cases: malformed JSON (skip with warning), empty files

### Task 2.2: Run migration

- [ ] Execute migration against all existing `state.json` files
- [ ] Verify all `state.yaml` files parse cleanly

---

## Phase 3: Update References

### Task 3.1: Agent command docs

**File(s):** `agents/commands/next-*.md`

- [ ] Grep for `state.json` across all agent command files
- [ ] Replace with `state.yaml` where referring to todo state

### Task 3.2: Documentation snippets

**File(s):** `docs/**/*.md`

- [ ] Grep for `state.json` references in doc snippets
- [ ] Update references that clearly point to todo state files
- [ ] Skip references to `.state.json` (MCP), `cron_state.json`, or `tui_state.json`
- [ ] Skip plan files (`docs/plans/`) — historical documents, not active references

### Task 3.3: Template files

**File(s):** `templates/todos/*` (if any reference state.json)

- [ ] Check and update any template references

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Update all test files that create/read `state.json` to use `state.yaml`
- [ ] Run `make test` — all tests must pass
- [ ] Key test files:
  - `tests/unit/test_todo_scaffold.py`
  - `tests/unit/test_todo_validation.py`
  - `tests/unit/test_next_machine_hitl.py`
  - `tests/unit/test_next_machine_state_deps.py`
  - `tests/unit/test_next_machine_breakdown.py`
  - `tests/unit/test_next_machine_group_sweep.py`
  - `tests/integration/test_state_machine_workflow.py`
  - `tests/unit/core/test_next_machine_deferral.py`
  - `tests/unit/core/test_roadmap.py`

### Task 4.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain
- [ ] Final grep for remaining `state.json` references — confirm only non-todo usages remain (MCP `.state.json`, `cron_state.json`, `tui_state.json`)

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
