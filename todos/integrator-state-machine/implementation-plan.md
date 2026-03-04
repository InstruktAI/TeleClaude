# Implementation Plan: integrator-state-machine

## Overview

Build a deterministic state machine for integration, following the `next_work()` pattern
in `teleclaude/core/next_machine/core.py`. The state machine orchestrates existing
integration primitives (queue, lease, clearance, follow-up) and returns structured
instruction blocks at decision points where agent intelligence is required.

Three layers: core state machine logic (new module), API route + CLI command (wire into
existing infrastructure), command spec update (replace prose with state machine calls).

## Phase 1: Core State Machine

### Task 1.1: Define checkpoint schema and integration states

**File(s):** `teleclaude/core/integration/state_machine.py`

- [ ] Define `IntegrationPhase` enum: `IDLE`, `LEASE_ACQUIRED`, `CANDIDATE_DEQUEUED`,
      `CLEARANCE_WAIT`, `MERGE_CLEAN`, `MERGE_CONFLICTED`, `AWAITING_COMMIT`,
      `COMMITTED`, `DELIVERY_BOOKKEEPING`, `PUSH_SUCCEEDED`, `PUSH_REJECTED`,
      `CLEANUP`, `CANDIDATE_DELIVERED`, `COMPLETED`
- [ ] Define `IntegrationCheckpoint` frozen dataclass: phase, candidate_key
      (slug, branch, sha), lease_token, items_processed, items_blocked,
      started_at, last_updated_at, error_context (optional dict for conflict files,
      rejection reason), pre_merge_head (SHA of main before merge — for re-entry detection)
- [ ] Implement atomic checkpoint read/write (JSON, temp file + os.replace — same
      pattern as `IntegrationQueue`)
- [ ] Implement checkpoint recovery: if phase is mid-candidate and lease is stale,
      re-queue the candidate and reset to IDLE

### Task 1.2: Implement `next_integrate()` entry point

**File(s):** `teleclaude/core/integration/state_machine.py`

- [ ] Implement `async def next_integrate(db: Db, slug: str | None, cwd: str, caller_session_id: str | None = None) -> str`
- [ ] Read checkpoint; if IDLE, acquire lease via `IntegrationLeaseStore`
- [ ] If lease acquired, pop next READY candidate via `IntegrationQueue.pop_next()`
- [ ] If slug provided and doesn't match next in queue, return error (queue is FIFO)
- [ ] Route to per-phase handler based on checkpoint phase
- [ ] Each handler: execute deterministic block, update checkpoint, return instruction block
- [ ] Use `format_tool_call()` / `format_error()` patterns from `next_work()` for output
- [ ] Log phase transitions: `NEXT_INTEGRATE_PHASE slug=X phase=Y decision=Z duration_ms=N`

### Task 1.3: Implement per-phase handlers

**File(s):** `teleclaude/core/integration/state_machine.py`

- [ ] **LEASE_ACQUIRED → CANDIDATE_DEQUEUED**: Pop candidate, emit `integration.candidate.dequeued`,
      write checkpoint, continue to clearance
- [ ] **CANDIDATE_DEQUEUED → CLEARANCE_WAIT**: Call `MainBranchClearanceProbe.check()`,
      if not cleared return wait instruction with blocking sessions and retry guidance,
      if cleared continue to merge
- [ ] **CLEARANCE_WAIT → MERGE_CLEAN/MERGE_CONFLICTED**: `git fetch origin`,
      `git checkout main`, `git pull --ff-only`, `git merge --squash {branch}`.
      On success: emit `integration.merge.succeeded`, checkpoint MERGE_CLEAN.
      On conflict: emit `integration.merge.conflicted`, checkpoint MERGE_CONFLICTED.
      Both return decision point instruction block
- [ ] **MERGE_CLEAN decision point returns:** diff stats, branch commit log
      (`git log main..{branch}`), requirements.md content, implementation-plan.md
      content — agent composes squash commit message and runs `git commit`
- [ ] **MERGE_CONFLICTED decision point returns:** conflicted file list, branch context —
      agent resolves conflicts, stages, composes commit message, runs `git commit`
- [ ] **AWAITING_COMMIT → COMMITTED**: Detect commit — if HEAD advanced past
      `pre_merge_head` and no `MERGE_HEAD` file exists, transition to COMMITTED.
      If MERGE_HEAD still exists (conflicts unresolved), re-prompt with remaining
      conflict files
- [ ] **COMMITTED → DELIVERY_BOOKKEEPING**: `telec roadmap deliver {slug}` (skip for
      bugs), `telec todo demo create {slug}` if demo exists, stage and commit
      delivery files, emit `integration.candidate.committed`
- [ ] **DELIVERY_BOOKKEEPING → PUSH_SUCCEEDED/PUSH_REJECTED**: `git push origin main`.
      On success: emit `integration.push.succeeded`, checkpoint PUSH_SUCCEEDED.
      On rejection: emit `integration.push.rejected`, checkpoint PUSH_REJECTED,
      return decision point (rejection reason — agent diagnoses and recovers)
- [ ] **PUSH_SUCCEEDED → CLEANUP**: Remove worktree, delete local and remote branch,
      remove todo directory, commit cleanup, emit `integration.candidate.delivered`,
      run `make restart`
- [ ] **CLEANUP → next candidate**: Mark queue item integrated, increment items_processed,
      reset phase to pop next candidate. If queue empty → COMPLETED
- [ ] **COMPLETED**: Release lease, emit `integration.completed` with summary
      (candidates processed, candidates blocked, total duration), return exit instruction
- [ ] **Blocked path** (from MERGE_CONFLICTED when agent signals unresolvable): emit
      `integration.candidate.blocked`, create follow-up via `BlockedFollowUpStore`,
      mark queue item blocked, increment items_blocked, continue to next candidate

### Task 1.4: Push rejection recovery detection

**File(s):** `teleclaude/core/integration/state_machine.py`

- [ ] After agent recovers from push rejection (pull, rebase, push), next
      `next_integrate()` call checks: is main pushed to origin? Compare local
      main HEAD with `git ls-remote origin main`. If equal: transition to
      PUSH_SUCCEEDED. If not: re-prompt with current state

## Phase 2: Lifecycle Events

### Task 2.1: Define integration lifecycle event types

**File(s):** `teleclaude/core/integration/events.py`

- [ ] Add lifecycle event type definitions alongside existing readiness events:
      `integration.started`, `integration.candidate.dequeued`,
      `integration.merge.succeeded`, `integration.merge.conflicted`,
      `integration.conflict.resolved`, `integration.candidate.committed`,
      `integration.push.succeeded`, `integration.push.rejected`,
      `integration.candidate.delivered`, `integration.candidate.blocked`,
      `integration.completed`
- [ ] Define payload schemas per event (per input.md lifecycle events table)
- [ ] All events carry integrator `session_id` as source

### Task 2.2: Wire event emission into state machine

**File(s):** `teleclaude/core/integration/state_machine.py`, `teleclaude/core/integration_bridge.py`

- [ ] Add emit helpers in `integration_bridge.py` for new lifecycle event types
      (extend existing `emit_deployment_*` pattern)
- [ ] Call emit at each state transition in the phase handlers
- [ ] Map existing bridge events to lifecycle events: `emit_deployment_completed` →
      `integration.candidate.delivered`, `emit_deployment_failed` →
      `integration.candidate.blocked`. Emit lifecycle events from state machine;
      keep bridge helpers for backward compatibility but avoid duplicate emissions

## Phase 3: CLI & API

### Task 3.1: Add API route `POST /todos/integrate`

**File(s):** `teleclaude/api/todo_routes.py`

- [ ] Add route handler mirroring `todo_work()`:
      ```python
      @router.post("/integrate")
      async def todo_integrate(
          slug: Annotated[str | None, Body()] = None,
          cwd: Annotated[str | None, Body()] = None,
          identity: CallerIdentity = Depends(CLEARANCE_TODOS_WORK),
      ) -> dict[str, str]:
          result = await next_integrate(db, slug, cwd, identity.session_id)
          return {"result": result}
      ```
- [ ] Wire `next_integrate` import from `teleclaude.core.integration.state_machine`

### Task 3.2: Add CLI command `telec todo integrate [<slug>]`

**File(s):** `teleclaude/cli/tool_commands.py`, `teleclaude/cli/telec.py`

- [ ] Add `handle_todo_integrate(args)` mirroring `handle_todo_work()`
- [ ] Call `tool_api_call("POST", "/todos/integrate", json_body={"cwd": cwd, "slug": slug})`
- [ ] Register in CLI surface (`CLI_SURFACE` dict and `CommandDef` entries in `telec.py`)
- [ ] Parse optional slug argument

## Phase 4: Command Update

### Task 4.1: Update `/next-integrate` command spec

**File(s):** `agents/commands/next-integrate.md`

- [ ] Replace prose integration steps with a loop calling `telec todo integrate`
- [ ] Document the three decision points and what the agent should do at each:
      - **Squash commit composition:** read the provided context (requirements, plan,
        branch commits, diff stats), compose a commit message capturing full delivery
        intent, run `git commit -m '<message>'`
      - **Conflict resolution:** read conflicted files, understand code context, resolve
        conflicts, stage resolutions, compose commit message, run `git commit`
      - **Push rejection recovery:** diagnose rejection, pull latest, rebase or re-merge,
        resolve new conflicts if any, retry push
- [ ] The command becomes: call `telec todo integrate`, read instruction block, execute
      decision, call again, repeat until exit instruction. On exit: self-end session
- [ ] Preserve behavioral guidance (commit message quality, conflict resolution approach)
      as agent-turn context within the command

---

## Phase 5: Validation

### Task 5.1: Tests

- [ ] Unit tests for checkpoint read/write/recovery (atomic writes, stale lease recovery)
- [ ] Unit tests for each phase handler (mock git operations and primitives)
- [ ] Integration test: full candidate lifecycle (merge → commit → push → cleanup)
- [ ] Test idempotency: call at same checkpoint state produces same output
- [ ] Test crash recovery: interrupt mid-phase, verify re-entry resumes correctly
- [ ] Test queue drain: multiple candidates processed in FIFO order
- [ ] Test blocked candidate: conflict → follow-up creation → skip to next
- [ ] Test clearance wait: probe returns not-cleared, verify wait instruction
- [ ] Test push rejection: verify decision point returns, verify recovery detection
- [ ] Run `make test`

### Task 5.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 6: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
