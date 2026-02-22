# Implementation Plan: bug-delivery-service

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fire-and-forget bug pipeline — `telec bugs report` captures a bug, dispatches an autonomous orchestrator that fixes, reviews, and merges via PR.

**Architecture:** Bugs are todos with a `bug.md` file instead of `input.md`. The `next_work()` state machine detects `bug.md`, skips the prepare phase, and dispatches a fix worker (with debugger skill) instead of a build worker. Finalize deletes the todo directory instead of archiving. A new `telec bugs` CLI command handles intake and listing.

**Tech Stack:** Python (Pydantic, asyncio), YAML, Markdown templates, telec CLI, next-machine state machine, agent command artifacts.

**Reference design:** `docs/plans/2026-02-22-bug-delivery-service-design.md`

---

### Task 1: Bug Template ✓

**Files:**

- Create: `templates/todos/bug.md`

**Steps:**

1. Create the template file with placeholders `{description}`, `{reporter}`, `{session_id}`, `{date}`:

```markdown
# Bug: {description}

## Symptom

{description}

## Discovery Context

Reported by: {reporter}
Session: {session_id}
Date: {date}

## Investigation

<!-- Fix worker fills this during debugging -->

## Root Cause

<!-- Fix worker fills this after investigation -->

## Fix Applied

<!-- Fix worker fills this after committing the fix -->
```

2. Commit: `feat(bugs): add bug.md template`

---

### Task 2: Bug Scaffold Function ✓

**Files:**

- Modify: `teleclaude/todo_scaffold.py`
- Create: `tests/unit/test_bug_scaffold.py`

**Steps:**

1. Write failing tests in `tests/unit/test_bug_scaffold.py`:
   - `test_create_bug_skeleton_creates_bug_md` — verifies `bug.md` content has description, reporter, session_id.
   - `test_create_bug_skeleton_creates_state_yaml_at_build_phase` — verifies `state.yaml` has `phase: in_progress`, `build: pending`, `review: pending`.
   - `test_create_bug_skeleton_does_not_create_requirements_or_plan` — verifies no `requirements.md`, `implementation-plan.md`, `quality-checklist.md`, or `input.md`.
   - `test_create_bug_skeleton_rejects_existing_dir` — raises `FileExistsError`.
   - `test_create_bug_skeleton_rejects_invalid_slug` — raises `ValueError`.

2. Run tests to verify they fail: `pytest tests/unit/test_bug_scaffold.py -v`

3. Implement `create_bug_skeleton` in `teleclaude/todo_scaffold.py`:
   - Define `_BUG_STATE` using the same Pydantic pattern as `_DEFAULT_STATE` but with `phase="in_progress"` and `dor=None`:
     ```python
     _BUG_STATE = TodoState(
         phase="in_progress",
         build="pending",
         review="pending",
         deferrals_processed=False,
         breakdown=BreakdownState(assessed=False, todos=[]),
         dor=None,
         review_round=0,
         max_review_rounds=3,
         review_baseline_commit="",
         unresolved_findings=[],
         resolved_findings=[],
     ).model_dump()
     ```
   - Function signature:
     ```python
     def create_bug_skeleton(
         project_root: Path,
         slug: str,
         description: str,
         *,
         reporter: str = "manual",
         session_id: str = "none",
     ) -> Path:
     ```
   - Validate slug with `SLUG_PATTERN`, check directory doesn't exist.
   - Read `bug.md` template via `_read_template("bug.md").format(...)`.
   - Serialize state with `yaml.dump(_BUG_STATE, ...)` (NOT json.dumps — project uses YAML).
   - Write `bug.md` and `state.yaml` only.

4. Run tests to verify they pass: `pytest tests/unit/test_bug_scaffold.py -v`

5. Commit: `feat(bugs): add create_bug_skeleton scaffold function`

---

### Task 3: CLI Commands — `telec bugs report` and `telec bugs list` ✓

**Files:**

- Modify: `teleclaude/cli/telec.py`

**Steps:**

1. Add `BUGS = "bugs"` to `TelecCommand` enum (after `ROADMAP`).

2. Add CLI_SURFACE entry for `"bugs"` with `report` and `list` subcommands:
   - `report`: args `<description>`, flags `--slug`, `--project-root`.
   - `list`: flags `--project-root`.

3. Add handler dispatch in `_handle_cli_command()`:

   ```python
   elif cmd_enum is TelecCommand.BUGS:
       _handle_bugs(args)
   ```

4. Implement `_handle_bugs()` router, `_handle_bugs_report()`, and `_handle_bugs_list()`:
   - `report`: parse args, auto-generate slug from description if not provided (prefix `fix-`), call `create_bug_skeleton()`.
   - `list`: scan `todos/` for dirs containing `bug.md`, read `state.yaml` to derive status, print table.
   - **Note:** `_handle_bugs_list` must read `state.yaml` (not `state.json`).

5. Commit: `feat(bugs): add telec bugs report and list CLI commands`

---

### Task 4: State Machine — Bug Detection in `next_work()` ✓

**Files:**

- Modify: `teleclaude/core/next_machine/core.py`
- Create: `tests/unit/test_bug_state_machine.py`

This is the critical integration. The `next_work()` function must detect `bug.md` and bypass roadmap/DOR/prepare gates.

**Steps:**

1. Write failing tests in `tests/unit/test_bug_state_machine.py`:
   - `test_is_bug_todo_true_when_bug_md_exists`
   - `test_is_bug_todo_false_when_no_bug_md`

2. Run tests to verify they fail.

3. Add `is_bug_todo()` helper near `check_file_exists()`:

   ```python
   def is_bug_todo(cwd: str, slug: str) -> bool:
       """Check if a todo is a bug (has bug.md)."""
       return check_file_exists(cwd, f"todos/{slug}/bug.md")
   ```

4. Run tests to verify they pass.

5. Modify `next_work()` at the slug validation block (~line 1967): bypass `slug_in_roadmap()` check when `is_bug_todo()` is true for the explicit slug.

6. Bypass DOR/readiness check (~line 1975): bugs start at `in_progress`, not `pending`, so the `is_ready_for_work` check is naturally skipped (it only triggers for `pending` phase items).

7. Modify precondition block (~line 2018-2034): when `is_bug_todo()` is true, skip the `requirements.md` and `implementation-plan.md` file checks.

8. Modify build dispatch (~line 2066): when `is_bug_todo()` is true, dispatch `next-bugs-fix` instead of `next-build`.

9. Add `POST_COMPLETION` entry for `"next-bugs-fix"` — same structure as `"next-build"` (read output, end session, mark build complete, call next_work).

10. Commit: `feat(bugs): detect bug.md in next-work, dispatch fix worker`

---

### Task 5: Bug Fix Worker Command ✓

**Files:**

- Create: `agents/commands/next-bugs-fix.md`

**Steps:**

1. Create `agents/commands/next-bugs-fix.md` with frontmatter (`argument-hint`, `description`).
2. Content: load `superpowers:systematic-debugging` skill, read `bug.md` as requirement, investigate, fix, update `bug.md` Investigation/Root Cause/Fix Applied sections, commit, report. Follow the same structure as `next-build.md` (Required reads, Purpose, Inputs, Outputs, Steps) but oriented toward debugging rather than plan execution.
3. Run `telec sync` to compile and distribute the artifact.
4. Commit: `feat(bugs): add next-bugs-fix worker command`

---

### Task 6: Review Adaptation — Teach Reviewer to Use `bug.md` ✓

**Files:**

- Modify: `agents/commands/next-review.md`

**Steps:**

1. Add a conditional block to the Steps section: if `todos/{slug}/bug.md` exists, use it as the requirement source instead of `requirements.md`. Verify fix addresses symptom, root cause analysis is sound, fix is minimal.
2. Run `telec sync`.
3. Commit: `feat(bugs): teach reviewer to use bug.md as requirement source`

---

### Task 7: Finalize Adaptation — Bug Cleanup ✓

**Files:**

- Modify: `teleclaude/core/next_machine/core.py`
- Modify: `agents/commands/next-finalize.md`

Two changes are needed. First, the `note` parameter on `format_tool_call()` instructs the **orchestrator** about bug-specific behavior. Second, the finalize **worker command** must also be taught to check for `bug.md` — the worker independently reads the finalize procedure (which says "append to delivered.md" and "remove from roadmap.yaml"), so it needs a conditional block to skip those steps for bugs.

**Steps:**

1. In `next_work()` at the finalize dispatch (~line 2155), check `is_bug_todo()` and pass a note:

   ```python
   is_bug = await asyncio.to_thread(is_bug_todo, worktree_cwd, resolved_slug)
   note = "BUG FIX: Skip delivered.md entry. Delete todo directory after merge." if is_bug else ""
   ```

2. Add a conditional block to `agents/commands/next-finalize.md` Steps section (same pattern as Task 6 for `next-review.md`): if `todos/{slug}/bug.md` exists, skip the "append to delivered.md" step and skip the "remove from roadmap.yaml" step (bugs are not in roadmap). Merge and push steps remain the same.

3. Run `telec sync`.

4. Commit: `feat(bugs): skip delivery log for bug fixes in finalize`

---

### Task 8: Bug Dispatcher — Worktree + Orchestrator Launch ✓

**Files:**

- Modify: `teleclaude/cli/telec.py` (extend `_handle_bugs_report`)

After creating the bug scaffold, create branch, worktree, and dispatch orchestrator.

**Steps:**

1. After `create_bug_skeleton()` in `_handle_bugs_report`, add:
   - Create git branch from main: `git branch {slug} main`
   - Create worktree: `git worktree add trees/{slug} {slug}`
   - Copy `bug.md` and `state.yaml` to worktree's `todos/{slug}/` dir.
   - Dispatch orchestrator via `TelecAPIClient.create_session()`:
     ```python
     api = TelecAPIClient()
     result = asyncio.run(api.create_session(
         computer="local",
         project_path=str(project_root),
         agent="claude",
         thinking_mode="slow",
         title=f"Bug fix: {slug}",
         message=f'Run teleclaude__next_work(slug="{slug}") and follow output verbatim until done.',
     ))
     ```
   - Print session ID and confirmation.
   - Handle errors gracefully (scaffold created but dispatch failed — tell user to run manually).

2. Commit: `feat(bugs): dispatch orchestrator from telec bugs report`

---

### Task 9: Verification ✓

**Steps:**

1. Run full test suite: `make test` — all pass.
2. Run lint: `make lint` — no errors.
3. Manual smoke test:
   - `telec bugs report "test bug description" --slug fix-test-bug`
   - `telec bugs list`
4. Clean up test artifacts:
   - `rm -rf todos/fix-test-bug trees/fix-test-bug`
   - `git branch -D fix-test-bug 2>/dev/null`
5. Final commit if any remaining changes.

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] All unit tests pass (`make test`)
- [ ] New tests: `test_bug_scaffold.py`, `test_bug_state_machine.py`

### Task 2.2: Quality Checks

- [ ] `make lint` passes
- [ ] No unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Requirements reflected in code changes
- [ ] Implementation tasks all marked `[x]`
- [ ] Deferrals documented if applicable
