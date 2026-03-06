# Implementation Plan: architecture-alignment-integration-pipeline

## Overview

Four-phase approach: (1) extend the phase schema to include finalize and add
the --cwd flag so mark-phase can target the correct state.yaml, (2) wire
post-finalize event emission into `next_work()` and update the orchestrator
guidance, (3) update the VCS policy, (4) validate. Each phase builds on the
previous.

## Phase 1: Phase Schema Extension & mark-phase --cwd Enabler

### Task 1.0: Extend PhaseName enum and API validation to include finalize

**File(s):** `teleclaude/core/next_machine/core.py` (line ~42-44),
`teleclaude/api/todo_routes.py` (line ~133)

- [ ] Add `FINALIZE = "finalize"` to the `PhaseName` enum (currently only `BUILD` and `REVIEW`)
- [ ] Update API validation at `todo_routes.py:133` to accept `"finalize"`:
      change `if phase not in ("build", "review")` to include `"finalize"`
- [ ] Update CLI handler docstring (`tool_commands.py:960`) to list finalize as a valid phase

### Task 1.1: Add --cwd argument to mark-phase CLI handler

**File(s):** `teleclaude/cli/tool_commands.py` (lines 949-994)

- [ ] Add `--cwd` to the argument parsing loop (alongside `--phase`, `--status`)
- [ ] When `--cwd` is provided, use it instead of `os.getcwd()` in the request body
- [ ] Validate the path exists before sending

### Task 1.2: Test Phase 1 changes

**File(s):** `tests/unit/test_tool_commands.py` (or appropriate test file)

- [ ] Test that `--phase finalize` is accepted (no HTTP 400)
- [ ] Test that `--cwd /some/path` overrides the default `os.getcwd()`
- [ ] Test that omitting `--cwd` preserves existing behavior

---

## Phase 2: Post-Finalize Event Emission

### Task 2.1: Add post-finalize detection in next_work()

**File(s):** `teleclaude/core/next_machine/core.py` (in `next_work()`, insert
the detection BEFORE the review-approved finalize dispatch at line ~2850, not
after line 3022 — line 3022 is where finalize is dispatched for the first time)

- [ ] Add a branch that detects `state.get("finalize") == "complete"` early in
      the routing logic, before the review-approved check dispatches finalize
- [ ] Guard: verify the worktree exists at `{cwd}/{WORKTREE_DIR}/{slug}`
- [ ] Derive branch: `git -C {worktree_path} rev-parse --abbrev-ref HEAD`
- [ ] Derive SHA: `git -C {worktree_path} rev-parse HEAD`
- [ ] Validate SHA is 40-char hex (matches existing validation in auto_enqueue)
- [ ] Call `await emit_deployment_started(slug, branch, sha, orchestrator_session_id=caller_session_id)`
- [ ] Return a COMPLETE response: "deployment.started event emitted for {slug}.
      Integrator will process the candidate. You can safely end your session."
- [ ] If worktree missing or SHA invalid: return error with clear diagnostic

### Task 2.2: Update POST_COMPLETION guidance for next-finalize

**File(s):** `teleclaude/core/next_machine/core.py` (lines 231-248,
`POST_COMPLETION["next-finalize"]`)

- [ ] Replace step 5 (`telec todo integrate {args}`) with:
      `telec todo mark-phase {args} --phase finalize --status complete --cwd {project_path}`
- [ ] Replace step 6 (report candidate queued) with:
      "Phase marked complete. Call `telec todo work` to emit integration event."
- [ ] Keep step 7 (`Call {next_call}`) — this is `telec todo work`
- [ ] Preserve all other steps (FINALIZE_READY confirmation, session end,
      error handling, no-op suppression)

### Task 2.3: Test post-finalize event emission

**File(s):** `tests/unit/test_next_work.py` (or appropriate test file)

- [ ] Test that `next_work()` emits `deployment.started` when finalize is complete
      and worktree exists with valid branch/sha
- [ ] Test that `next_work()` returns error when worktree is missing
- [ ] Test that the COMPLETE response includes the expected message
- [ ] Mock `emit_deployment_started` to verify it receives correct arguments

---

## Phase 3: Policy Update

### Task 3.1: Update Version Control Safety policy

**File(s):** `docs/global/software-development/policy/version-control-safety.md`

- [ ] Change state-files commit strategy: workers commit all dirty files
      (including `state.yaml`, `roadmap.yaml`) at end of work
- [ ] Add rationale: worktree branches only reach main through the integrator;
      committing state files creates a complete audit trail per worker session
- [ ] Keep the non-blocking treatment of orchestrator-managed drift (workers
      should not _block_ on these files being dirty, AND should commit them)
- [ ] Run `telec sync` to propagate the policy change

---

## Phase 4: Validation

### Task 4.1: Tests

- [ ] Run `make test` — all existing tests pass
- [ ] New tests for --cwd and post-finalize emission pass

### Task 4.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

## Notes for Builder

- **Import**: `emit_deployment_started` is in `teleclaude.core.integration_bridge`.
  It is async and already exists — do not create a new function.
- **State detection**: After Task 1.0, `mark-phase --phase finalize --status complete`
  will write `finalize: complete` to `state.yaml`. `next_work()` reads this with
  `state.get("finalize")`. The PhaseName extension in Task 1.0 is the prerequisite.
- **Insertion point**: The post-finalize detection branch (Task 2.1) must go BEFORE
  the review-approved check that dispatches finalize (line ~3022). If finalize is
  already complete, `next_work()` should emit the event and return COMPLETE — it
  should not re-dispatch finalize.
- **Backward compatibility**: The old `telec todo integrate` path MUST still work. Both
  paths (event-driven and direct) can coexist until `next-machine-old-code-cleanup` lands.
- **Dependency**: `next-machine-old-code-cleanup` depends on this todo. Once verified,
  it strips the old manual path.
