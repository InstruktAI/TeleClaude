# Implementation Plan: architecture-alignment-integration-pipeline

## Overview

Three-phase approach: (1) enable the --cwd flag so mark-phase can target the
correct state.yaml, (2) wire post-finalize event emission into `next_work()`
and update the orchestrator guidance, (3) update the VCS policy. Each phase
builds on the previous.

## Phase 1: mark-phase --cwd Enabler

### Task 1.1: Add --cwd argument to mark-phase CLI handler

**File(s):** `teleclaude/cli/tool_commands.py` (lines 949-994)

- [ ] Add `--cwd` to the argument parsing loop (alongside `--phase`, `--status`)
- [ ] When `--cwd` is provided, use it instead of `os.getcwd()` in the request body
- [ ] Validate the path exists before sending

### Task 1.2: Test --cwd flag

**File(s):** `tests/unit/test_tool_commands.py` (or appropriate test file)

- [ ] Test that `--cwd /some/path` overrides the default `os.getcwd()`
- [ ] Test that omitting `--cwd` preserves existing behavior

---

## Phase 2: Post-Finalize Event Emission

### Task 2.1: Add post-finalize detection in next_work()

**File(s):** `teleclaude/core/next_machine/core.py` (in `next_work()`, after the
review-approved / finalize dispatch section around line 3022)

- [ ] After the existing finalize dispatch check, add a branch that detects
      finalize is marked complete in state.yaml
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
- **State detection**: Investigate how `mark-phase` stores phase status in `state.yaml`.
  If there is no `finalize` field yet, extend the schema minimally. The field must be
  readable by `next_work()`.
- **Backward compatibility**: The old `telec todo integrate` path MUST still work. Both
  paths (event-driven and direct) can coexist until `next-machine-old-code-cleanup` lands.
- **Dependency**: `next-machine-old-code-cleanup` depends on this todo. Once verified,
  it strips the old manual path.
