# Implementation Plan: lifecycle-enforcement-gates

## Overview

This delivery moves the lifecycle from trust-based to evidence-based. Two layers of change: CLI tooling (`telec todo demo` subcommands) and state machine enforcement (`next_work()` build gates). The approach is bottom-up: build the tools first, then wire them into the state machine.

Documentation alignment (procedures, specs, templates) is split to `lifecycle-enforcement-docs`.

## Phase 1: CLI — `telec todo demo` Subcommand Refactor

### Task 1.1: Refactor `telec todo demo` into subcommands: `validate`, `run`, `create`

**File(s):** `teleclaude/cli/telec.py`

The current demo runner (lines ~1260-1380) is a monolith. Split into three explicit subcommands while preserving the no-subcommand listing behavior.

- [ ] Add `validate` subcommand: structural check only — parse demo.md, check for `<!-- no-demo: reason -->` marker (exit 0 + log reason if found), check for presence of at least one non-skipped bash block (exit 0 if found, exit 1 if not). No execution of blocks.
- [ ] Add `run` subcommand: extract and execute bash blocks sequentially (current behavior). Fix the silent-pass bug: exit 1 when no executable blocks exist (lines 1355-1357 and 1367-1369 currently exit 0 — must exit 1).
- [ ] Add `create` subcommand: promote `todos/{slug}/demo.md` to `demos/{slug}/demo.md`. Generate minimal `snapshot.json` with `{slug, title, version}` — read title from demo.md H1, read version from `pyproject.toml`. Create `demos/{slug}/` directory. Fail if source demo.md doesn't exist.
- [ ] Preserve no-subcommand behavior: `telec todo demo` (no args) lists available demos. `telec todo demo {slug}` (no subcommand but with slug) — default to `run` for backward compatibility, print deprecation notice suggesting `telec todo demo run {slug}`.

### Task 1.2: Add `<!-- no-demo: reason -->` escape hatch support

**File(s):** `teleclaude/cli/telec.py`

- [ ] In `validate` subcommand: parse first 10 lines of demo.md for `<!-- no-demo: ... -->` HTML comment. If found, extract reason text, print it, exit 0.
- [ ] In `run` subcommand: same check — if `<!-- no-demo -->` present, print reason, exit 0 (nothing to run).
- [ ] Ensure `create` subcommand still promotes the file even with `<!-- no-demo -->` (the demo.md is still a valid artifact, just one without executable validation).

### Task 1.3: Tests for demo subcommands

**File(s):** `tests/test_demo_cli.py` (new) or extend existing test file

- [ ] Test `validate` exits 0 on demo.md with bash blocks
- [ ] Test `validate` exits 1 on scaffold template (no blocks)
- [ ] Test `validate` exits 0 on `<!-- no-demo: reason -->` and captures reason in output
- [ ] Test `run` exits 1 on scaffold template (no blocks) — the silent-pass fix
- [ ] Test `run` executes blocks and reports pass/fail
- [ ] Test `create` promotes demo.md and generates snapshot.json
- [ ] Test `create` fails when source demo.md missing
- [ ] Test no-subcommand listing still works

---

## Phase 2: State Machine — Build Gates and Flow Fixes in `next_work()`

### Task 2.1: Add build gate validation between build-complete and review-dispatch

**File(s):** `teleclaude/core/next_machine/core.py`

The insertion point is between `is_build_complete()` check (line 2123) and the review dispatch block (line 2155). Currently, when build is complete, the machine immediately checks review status and dispatches review. The new flow:

```
is_build_complete? -> YES -> run gates -> gates pass? -> YES -> check review status
                                                      -> NO  -> reset build to started, return message-builder instruction
```

- [ ] After `is_build_complete()` returns True (line 2123), add a new gate-validation block before falling through to the review check (line 2155).
- [ ] Run `make test` in the worktree directory via subprocess with a timeout (e.g., 120 seconds). Capture exit code and stderr/stdout.
- [ ] Run `telec todo demo validate {slug}` in the worktree directory via subprocess with a timeout (e.g., 30 seconds). Capture exit code and output.
- [ ] If both pass (exit 0): fall through to review dispatch as before.
- [ ] If either fails: call `mark_phase(worktree_cwd, slug, "build", "started")` to reset build status. Return a formatted instruction telling the orchestrator to send the builder a message with the failure details. Do NOT instruct session end. Include the gate output so the builder knows what failed.
- [ ] After gate reset, call `sync_slug_todo_from_worktree_to_main(cwd, slug)` to propagate the reset state back to main. Note: this function exists (line 1372) but is not currently called from `next_work()` — this is a new wiring.

### Task 2.2: Change POST_COMPLETION for `next-build` and `next-bugs-fix`

**File(s):** `teleclaude/core/next_machine/core.py`

The current `POST_COMPLETION["next-build"]` (lines 82-87) tells the orchestrator to:

1. Read worker output
2. End session
3. Mark phase build=complete
4. Call next_work

This must change so the orchestrator does NOT end the session before gates pass:

- [ ] Update `POST_COMPLETION["next-build"]` to:
  1. Read worker output via get_session_data
  2. `teleclaude__mark_phase(slug="{args}", phase="build", status="complete")`
  3. Call `{next_call}` — this runs the gates in `next_work()`
  4. If `next_work` says gates passed: THEN end session and continue
  5. If `next_work` says gates failed: send the builder the failure message, wait for builder to fix, repeat from step 1
- [ ] Apply same change to `POST_COMPLETION["next-bugs-fix"]` (lines 88-93).

### Task 2.3: Format the gate-failure response

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Create a new formatter function (e.g., `format_build_gate_failure()`) that produces a clear instruction block for the orchestrator. The block must:
  - State which gate(s) failed and the output
  - Tell orchestrator to send this message to the builder session (not end it)
  - Tell orchestrator to wait for builder to report done again
  - Tell orchestrator to then call `mark_phase(build=complete)` + `next_work()` again
- [ ] Ensure the response format is consistent with existing `format_tool_call()` / `format_error()` patterns.

### Task 2.4: Make `next_work()` read-only — defer state marking to orchestrator

**File(s):** `teleclaude/core/next_machine/core.py`

Currently `next_work()` mutates worktree state as a side effect before returning output (lines 2117-2120: sets `phase: in_progress`, lines 2123-2126: sets `build: started`). If the orchestrator decides not to continue (user says no, session closes), the worktree retains `build: started` with nobody working on it. Main's state.yaml stays at `pending` (no worktree→main sync exists in this path), so the next `next_work()` call correctly resumes — but the worktree state is inconsistent.

Fix: remove premature state mutations from `next_work()` when it's about to dispatch a new build. Move them into the output instructions so the orchestrator only executes them when it actually dispatches.

- [ ] Remove `set_item_phase(in_progress)` call (lines 2117-2120) from inside `next_work()`.
- [ ] Remove `mark_phase(build, started)` call (lines 2123-2126) from inside `next_work()`.
- [ ] Add these as explicit steps in the `format_tool_call` output, as a "BEFORE DISPATCHING" block:
  1. `teleclaude__mark_phase(slug="{slug}", phase="build", status="started")`
     The orchestrator calls it only when committing to dispatch.
- [ ] Ensure `set_item_phase(in_progress)` is also triggered — either as a side effect of `mark_phase(build, started)` (if phase is still pending, transition it), or as a separate instruction in the output.

### Task 2.5: Add `make restart` to POST_COMPLETION for `next-finalize`

**File(s):** `teleclaude/core/next_machine/core.py`

After finalize, main has new code but the daemon is still running the old version. The next `next_work()` call uses stale code.

- [ ] Add `make restart` step to `POST_COMPLETION["next-finalize"]` (lines 113-122), between cleanup (step 3) and the `next_work()` call (step 4):
  ```
  3. CLEANUP (orchestrator-owned):
     a. git worktree remove trees/{args} --force
     b. git branch -d {args}
     c. rm -rf todos/{args}
     d. git add -A && git commit -m "chore: cleanup {args}"
  4. make restart
  5. Call {next_call}
  ```
- [ ] The orchestrator runs `make restart` via Bash tool. Brief restart, daemon picks up merged code, then `next_work()` runs on fresh code.

### Task 2.6: Tests for state machine changes

**File(s):** `tests/test_next_machine.py` or appropriate existing test file

- [ ] Test that `next_work()` runs gates when build is complete
- [ ] Test that passing gates lead to review dispatch
- [ ] Test that failing `make test` resets build to `started` and returns gate-failure instruction
- [ ] Test that failing `telec todo demo validate` resets build to `started` and returns gate-failure instruction
- [ ] Test that gate failure response includes failure output for the builder
- [ ] Test that `next_work()` does NOT mutate state when returning a new build dispatch — output contains marking instructions but state.yaml is unchanged
- [ ] Test that POST_COMPLETION for `next-finalize` includes `make restart` step

---

## Phase 3: snapshot.json Reduction

### Task 3.1: Decide and implement snapshot.json strategy

**File(s):** `teleclaude/cli/telec.py`, `demos/*/snapshot.json` (existing)

The `acts` narrative and `metrics` in snapshot.json duplicate `delivered.yaml` and git history. Only `version` is unique (for semver gating).

- [ ] Reduce snapshot.json schema to `{slug, title, version}`. Remove `metrics`, `acts`, `delivered`, `commit` fields.
- [ ] Update `telec todo demo create` to generate the reduced snapshot.
- [ ] Update `telec todo demo` listing to work with reduced snapshot (it already reads slug, title, version, delivered — delivered can come from `delivered.yaml` or be dropped from listing).
- [ ] Do NOT retroactively modify existing snapshots — they continue to work via backward-compatible field access.

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] All new tests from Tasks 1.3 and 2.6 pass
- [ ] Run `make test` — all existing tests pass
- [ ] Run `make lint`

### Task 4.2: Integration verification

- [ ] Create a test demo.md with bash blocks, run `telec todo demo validate` — exits 0
- [ ] Create a test demo.md with `<!-- no-demo: testing -->`, run `telec todo demo validate` — exits 0, logs reason
- [ ] Use the scaffold template, run `telec todo demo validate` — exits 1
- [ ] Run `telec todo demo` (no args) — listing still works

### Task 4.3: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
