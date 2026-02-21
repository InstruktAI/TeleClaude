# Implementation Plan: unified-roadmap-assembly

## Overview

Extract the rich todo assembly logic from `command_handlers.list_todos()` into a sync core function, make `telec roadmap` use it, add `--json` and icebox flags. The data model (`TodoInfo`) stays unchanged — this is a plumbing consolidation.

## Phase 1: Extract core function

### Task 1.1: Create `assemble_todos()` in command_handlers

**File(s):** `teleclaude/core/command_handlers.py`

- [ ] Extract the body of `list_todos()` (lines 502-735) into a new sync function: `assemble_todos(project_path: str, include_icebox: bool = False, icebox_only: bool = False) -> list[TodoInfo]`
- [ ] Move all nested helpers (`slugify_heading`, `parse_icebox_slugs`, `read_todo_metadata`, `append_todo`, `infer_input_description`) into the new function
- [ ] Add icebox logic: when `icebox_only=True`, load only `load_icebox()` entries; when `include_icebox=True`, load both roadmap and icebox entries
- [ ] Preserve the orphan-directory scan (dirs not in roadmap/icebox)
- [ ] Preserve the breakdown/container-child injection pass
- [ ] Make `list_todos()` a thin async wrapper: `return assemble_todos(project_path)`

Note: the function stays in `command_handlers.py` for now rather than a new file — it uses the same helpers and `TodoInfo` import. Moving to a dedicated module is a future simplification if needed.

### Task 1.2: Verify API and TUI unchanged

**File(s):** (no changes expected)

- [ ] Run `make test` — existing tests cover `list_todos()` behavior
- [ ] Verify TUI preparation view still loads todos correctly (manual check via TUI)

## Phase 2: CLI integration

### Task 2.1: Replace `_handle_roadmap_show()` with core function call

**File(s):** `teleclaude/cli/telec.py`

- [ ] Replace `_handle_roadmap_show()` body: call `assemble_todos()` instead of manual `load_roadmap()` + state reading
- [ ] Render rich terminal output from `TodoInfo` objects: grouped by `.group`, showing slug, DOR score, build/review status, findings count, deps
- [ ] Add `--json` flag: output `[{slug, status, description, dor_score, build_status, review_status, ...}]` as JSON
- [ ] Add `-i` / `--include-icebox` flag: pass `include_icebox=True` to `assemble_todos()`
- [ ] Add `-o` / `--icebox-only` flag: pass `icebox_only=True` to `assemble_todos()`

### Task 2.2: Update CLI_SURFACE

**File(s):** `teleclaude/cli/telec.py`

- [ ] Add `Flag("--json", desc="Output as JSON")` to the roadmap CommandDef flags
- [ ] Add `Flag("-i", "--include-icebox", desc="Include icebox items")` to roadmap flags
- [ ] Add `Flag("-o", "--icebox-only", desc="Show only icebox items")` to roadmap flags

---

## Phase 3: Validation

### Task 3.1: Tests

- [ ] Add unit test for `assemble_todos()` with a fixture project (roadmap.yaml + state.json + icebox.yaml)
- [ ] Test `icebox_only=True` returns only icebox entries
- [ ] Test `include_icebox=True` returns both
- [ ] Test `--json` flag produces valid JSON matching TodoInfo fields
- [ ] Run `make test`

### Task 3.2: Quality Checks

- [ ] Run `make lint`
- [ ] Run `./tools/checks/check-cli-help.sh` — verify new flags render in `-h`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
