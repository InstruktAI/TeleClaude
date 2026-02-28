# Implementation Plan: integrate-session-lifecycle-into-next-work

## Overview

Three workstreams: (1) artifact verification CLI gate, (2) direct peer conversation for review friction, (3) session lifecycle principle wiring. The artifact verification is a standalone function that can be built and tested independently. The peer conversation requires modifying POST_COMPLETION and state machine routing in `core.py`. The principle wiring is a documentation change.

Build order: verification gate first (independent, testable), then peer conversation (depends on understanding the current POST_COMPLETION flow), then principle wiring (trivial).

## Phase 1: Artifact Verification Gate

### Task 1.1: Implement `verify_artifacts()` in core.py

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Add `verify_artifacts(worktree_cwd: str, slug: str, phase: str) -> tuple[bool, str]` function
- [ ] Build phase checks:
  - `implementation-plan.md` exists and all task checkboxes are `[x]` (no unchecked `[ ]` remain)
  - At least one commit exists on the worktree branch (not just the branch creation commit)
  - `quality-checklist.md` Build Gates section has at least one checked item
- [ ] Review phase checks:
  - `review-findings.md` exists and is not the scaffold template (detect template markers: empty `## Findings` or placeholder text)
  - A verdict line (`APPROVE` or `REQUEST CHANGES`) is present in `review-findings.md`
  - `quality-checklist.md` Review Gates section has at least one checked item
- [ ] General checks (all phases):
  - `state.yaml` is parseable YAML
  - `state.yaml` phase field is consistent with the claimed status (e.g., if claiming build complete, `build` field should not be `pending`)
- [ ] Return `(passed: bool, report: str)` where report lists each check with pass/fail

### Task 1.2: Add CLI command `telec todo verify-artifacts`

**File(s):** `teleclaude/cli/telec.py`, `teleclaude/cli/tool_commands.py`

- [ ] Register `verify-artifacts` as a subcommand under `todo` in `CLI_SURFACE`
- [ ] Accept arguments: `<slug>` (required), `--phase <build|review>` (required), `--cwd` (optional, defaults to project root)
- [ ] Call `verify_artifacts()` and print the report
- [ ] Exit 0 on pass, exit 1 on failure

### Task 1.3: Integrate verification into state machine

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] After `run_build_gates()` passes in `next_work()`, also call `verify_artifacts(worktree_cwd, slug, "build")` — both must pass before dispatching review
- [ ] In `POST_COMPLETION["next-review"]`: add instruction for orchestrator to run `telec todo verify-artifacts <slug> --phase review` before processing the verdict
- [ ] If verification fails, format an error similar to `format_build_gate_failure()` that tells the orchestrator what's missing

---

## Phase 2: Direct Peer Conversation for Review Friction

### Task 2.1: Modify POST_COMPLETION for next-review

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Split `POST_COMPLETION["next-review"]` into two paths:
  - **APPROVE path** (unchanged): end session, mark phase approved, call next_work
  - **REQUEST CHANGES path** (new): do NOT end reviewer session. Instead:
    1. Save `reviewer_session_id` (the session that just completed)
    2. Mark phase as `changes_requested`
    3. Dispatch a fixer worker via `telec sessions run --command /next-fix-review --args <slug> ...`
    4. Save `fixer_session_id`
    5. Establish direct link: `telec sessions send <reviewer_session_id> "A fixer has been dispatched at session <fixer_session_id>. Establish direct link and iterate on review-findings.md together. When satisfied, update review-findings.md verdict to APPROVE." --direct`
    6. Send fixer context: `telec sessions send <fixer_session_id> "Reviewer is active at session <reviewer_session_id>. Establish direct link and iterate on review-findings.md together." --direct`
    7. Start heartbeat timer
    8. Wait for fixer completion notification
    9. On fixer completion: read `review-findings.md` verdict
    10. If APPROVE: end both sessions, mark phase approved, call next_work
    11. If still REQUEST CHANGES: increment review round, check limit, loop or apply closure

### Task 2.2: Update state machine routing for active reviewer

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] In the `review_status == CHANGES_REQUESTED` branch of `next_work()`:
  - Current behavior (dispatch fix-review) becomes the **fallback** path
  - Add a `note` to the `format_tool_call()` output indicating that if a reviewer session is still alive from the previous review dispatch, the orchestrator should use the direct conversation pattern from POST_COMPLETION instead of re-entering the state machine
  - The state machine itself remains stateless — it always returns "dispatch fix-review" for changes_requested. The orchestrator's POST_COMPLETION instructions handle the peer conversation before calling next_work again

### Task 2.3: Update next-fix-review command for peer awareness

**File(s):** `agents/commands/next-fix-review.md`

- [ ] Add guidance that when a `--direct` peer link is established with a reviewer, the fixer should:
  - Address findings iteratively with reviewer feedback
  - Signal completion through the normal FIX COMPLETE report format
  - Not self-terminate (orchestrator always ends children)
- [ ] Add note that the fixer may receive direct messages from the reviewer during work — this is expected and the fixer should respond to review feedback inline

---

## Phase 3: Session Lifecycle Principle Wiring

### Task 3.1: Add required read to next-work command

**File(s):** `agents/commands/next-work.md`

- [ ] Add `@~/.teleclaude/docs/general/principle/session-lifecycle.md` to the `## Required reads` section
- [ ] Run `telec sync` to regenerate artifacts

### Task 3.2: Strengthen POST_COMPLETION lifecycle discipline

**File(s):** `teleclaude/core/next_machine/core.py`

- [ ] Add artifact verification step to all POST_COMPLETION entries before ending sessions
- [ ] Add explicit "verify artifact delivery before ending session" instruction to each POST_COMPLETION block
- [ ] Ensure every POST_COMPLETION path ends with `telec sessions end <session_id>` as the last action before calling next_work (already true for most, verify consistency)
- [ ] Add signal session concept: if a worker reports a non-recoverable error, POST_COMPLETION should instruct the orchestrator to keep the session alive as a signal for human attention instead of ending it

---

## Phase 4: Validation

### Task 4.1: Tests for verify_artifacts

**File(s):** `tests/unit/test_next_machine_verify_artifacts.py` (new file)

- [ ] Test build phase verification: pass case (all tasks checked, commits exist, quality checklist populated)
- [ ] Test build phase verification: fail case (unchecked tasks, no commits, empty checklist)
- [ ] Test review phase verification: pass case (findings exist, verdict present, checklist populated)
- [ ] Test review phase verification: fail case (template-only findings, missing verdict)
- [ ] Test general checks: malformed state.yaml, inconsistent phase status
- [ ] Test edge cases: missing files, empty files, partially filled templates

### Task 4.2: Quality Checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 5: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
