# Implementation Plan: demo-runner

## Overview

Replace the post-finalize demo creation flow with build-phase demo artifacts and a CLI runner. Simplify folder naming from numbered to slug-based. The CLI runner (~80-100 lines) is the only substantial new code; the rest is spec/doc edits, test updates, agent command rewrite, and template config.

## Phase 1: Schema & Spec Updates

### Task 1.1: Update demo artifact spec

**File(s):** `docs/project/spec/demo-artifact.md`

- [x] Change folder convention from `demos/NNN-{slug}/` to `demos/{slug}/`
- [x] Remove sequence number references and `sequence` field from schema
- [x] Add `demo` field (optional string) to `snapshot.json` schema
- [x] Document that `demo` is a shell command executed from the demo folder directory
- [x] Remove `demo.sh` contract section (steps 7-8 in current spec)
- [x] Add backward compatibility note: runner warns when `demo` field is absent
- [x] Fix delivery file reference: `delivered.md` → `delivered.yaml`

### Task 1.2: Migrate existing demo folders

**File(s):** `demos/001-tui-markdown-editor/`, `demos/002-themed-primary-color/`

- [ ] Rename `demos/001-tui-markdown-editor/` → `demos/tui-markdown-editor/`
- [ ] Rename `demos/002-themed-primary-color/` → `demos/themed-primary-color/`
- [ ] Remove `sequence` field from both `snapshot.json` files
- [ ] Remove `demo.sh` from both folders

---

## Phase 2: CLI Runner

### Task 2.1: Add `demo` subcommand to CLI surface

**File(s):** `teleclaude/cli/telec.py` (lines ~143-162, `CLI_SURFACE["todo"].subcommands`)

- [ ] Add `"demo"` to `CLI_SURFACE["todo"].subcommands` with description "Run or list demo artifacts", args `[slug]`, and `--project-root` flag

### Task 2.2: Wire dispatcher

**File(s):** `teleclaude/cli/telec.py` (lines ~1050-1064, `_handle_todo()`)

- [ ] Add `elif subcommand == "demo":` branch calling `_handle_todo_demo(args[1:])`

### Task 2.3: Implement `_handle_todo_demo()`

**File(s):** `teleclaude/cli/telec.py`

- [ ] Read project version from `pyproject.toml` (currently `0.1.0`)
- [ ] Scan `demos/*/snapshot.json` for available demos
- [ ] No slug: list demos as a table (title, slug, version, delivered date). Read `delivered_date` field with fallback to `delivered` for forward compatibility.
- [ ] With slug: find `demos/{slug}/snapshot.json`
- [ ] Semver gate: compare major versions, skip with message if incompatible
- [ ] Missing `demo` field: warn and exit 0
- [ ] Execute `demo` field command via `subprocess.run(shell=True, cwd=demo_folder)`
- [ ] Nonexistent slug: print error, exit 1
- [ ] Empty demos directory: print "No demos available", exit 0

---

## Phase 3: Lifecycle Integration

### Task 3.1: Decouple demo from finalize

**File(s):** `teleclaude/core/next_machine/core.py` (lines ~106-124, `POST_COMPLETION`)

- [ ] Remove step 3 (DEMO) from `POST_COMPLETION["next-finalize"]` (lines ~114-117)
- [ ] Renumber remaining steps (CLEANUP becomes step 3, next_call becomes step 4)
- [ ] Remove `POST_COMPLETION["next-demo"]` entry entirely (lines ~120-124) — no longer needed as a post-completion step

### Task 3.2: Rewrite `/next-demo` command

**File(s):** `agents/commands/next-demo.md`

- [ ] Rewrite as the ceremony host:
  - **No slug**: scan `demos/*/snapshot.json`, list available demos (title, slug, version), ask which one to present
  - **With slug**: present that demo — run `telec todo demo <slug>`, then render a celebration widget using snapshot data (title, metrics table, narrative acts)
- [ ] Remove all post-finalize narrative composition, `demo.sh` generation, and sequence numbering logic
- [ ] The command is purely presentation — no build guidance (that belongs in the procedure doc)
- [ ] Keep the `render_widget` celebration pattern — the widget renders snapshot data, not AI-composed narrative

### Task 3.3: Update quality checklist template

**File(s):** `templates/todos/quality-checklist.md`

- [ ] Add `- [ ] Demo is runnable and verified` to Build Gates section (after "Code committed")

### Task 3.4: Update demo procedure doc

**File(s):** `docs/global/software-development/procedure/lifecycle/demo.md`

- [ ] Update: demo is created during build, not after finalize
- [ ] Add builder guidance: how to create the `demo` field in `snapshot.json` (shell command that shows the feature)
- [ ] Presentation uses `telec todo demo <slug>` or `/next-demo` conversational interface
- [ ] Remove `demo.sh` references and sequence numbering
- [ ] Fix delivery file reference: `delivered.md` → `delivered.yaml`
- [ ] Keep the Five Acts narrative structure — still captured in `snapshot.json`, now by the builder

---

## Phase 4: Validation

### Task 4.1: Update tests

**File(s):** `tests/unit/test_next_machine_demo.py`

- [ ] Remove tests for `demo.sh` existence and executability (`test_demo_sh_semver_*` tests, lines ~206-359)
- [ ] Remove tests for demo dispatch in `POST_COMPLETION["next-finalize"]` (`test_post_completion_finalize_includes_demo_step`, `test_post_completion_finalize_demo_before_cleanup`, `test_post_completion_finalize_demo_is_non_blocking`)
- [ ] Remove test for `POST_COMPLETION["next-demo"]` entry (`test_post_completion_has_next_demo_entry`, `test_post_completion_next_demo_has_end_session`)
- [ ] Update folder naming expectations: slug-based, no sequence numbers
- [ ] Keep schema field tests but note that actual deployed snapshots use variant names — tests validate the spec-standard schema for new demos
- [ ] Add tests for CLI runner: list, run by slug, semver gate, missing demo field, nonexistent slug, empty demos dir
- [ ] Ensure `make test` passes

### Task 4.2: Quality checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

---

## Build Sequence

Phases are sequential. Within each phase, tasks can be done in order. Estimated total: single focused builder session.

| Phase | Focus                 | New Code               |
| ----- | --------------------- | ---------------------- |
| 1     | Spec + migration      | 0 lines (edits only)   |
| 2     | CLI runner            | ~80-100 lines          |
| 3     | Lifecycle integration | Doc/config edits       |
| 4     | Tests                 | Update + new CLI tests |
| 5     | Final checks          | Verification only      |
