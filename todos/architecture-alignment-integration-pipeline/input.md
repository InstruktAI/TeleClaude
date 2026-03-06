# architecture-alignment-integration-pipeline — Input

## Architecture Alignment: Event-Driven Integration Pipeline

### Summary
Consolidation of findings from architecture review of chiptunes-audio finalize/integration flow. Aligns worker commit strategy, state machine responsibilities, orchestrator role boundaries, and event emission wiring.

### Critical Changes Required

#### 1. State Files Commit Strategy (Policy Change)
**Status:** Design finalized, requires documentation update
**Finding:** Workers should commit ALL dirty files (including state.yaml, roadmap.yaml) at end of work
**Rationale:**
- Simplifies rules (one rule: commit everything)
- Keeps main clean (only integrator pushes main)
- Each worker's commit shows orchestrator's phase marking + their work
- Creates clean audit trail through lifecycle
**Action:** Update Version Control Safety policy

#### 2. mark-phase --cwd Flag (Feature Implementation)
**Status:** Identified gap, needs implementation
**Gap:** CLI captures os.getcwd() with no override. Wrong state.yaml updated if orchestrator runs elsewhere
**Solution:** Add --cwd flag to handle_todo_mark_phase CLI handler
**Implementation:**
- Add --cwd argument parsing (tool_commands.py:850)
- Pass cwd through to API endpoint (already accepts it)
- Update state machine to emit: telec todo mark-phase {slug} --phase X --status Y --cwd {worktree_path}
**Files:** tool_commands.py, next_machine/core.py

#### 3. Orchestrator Role Boundary (Critical Redesign)
**Current (Wrong):** Orchestrator derives branch/sha, calls emit_deployment_started()
**Correct:** Orchestrator only continues state machine; state machine handles all post-finalize logic
**Rationale:** State machine is director. Orchestrator purely executes instructions.
**Flow:**
1. Orchestrator: telec todo work {slug} (continue)
2. State machine: detects finalize complete
3. State machine: derives branch/sha from worktree git
4. State machine: calls emit_deployment_started(slug, branch, sha, ...)
5. State machine: returns COMPLETE ("you can safely die")
6. Orchestrator: ends session
**Files:** next_machine/core.py (next_work function)

#### 4. State Machine Post-Finalize Gap (Critical Implementation)
**Status:** Critical blocker
**Gap:** emit_deployment_started() never called after FINALIZE_READY consumed
**Impact:** Integration cartridge never wakes, integrator never spawned
**Implementation in next_work():**
- Detect finalize complete (review: approved + worktree merged)
- git -C {worktree} rev-parse --abbrev-ref HEAD → branch
- git -C {worktree} rev-parse HEAD → sha  
- await emit_deployment_started(slug, branch, sha, orchestrator_session_id={session_id})
- Return COMPLETE with "work done, you can safely die" message
**Files:** next_machine/core.py (next_work), integration_bridge.py (emit_deployment_started exists)

#### 5. Auto-Commits Conversion (Integrator Workflow Redesign)
**Status:** Identified, requires conversion not removal
**Current:** _step_committed() and _do_cleanup() auto-commit via _run_git
**Problem:** Violates "state machine directs, AI executes" model
**Solution:** Convert to AI-directed instructions in integrator workflow:
- _step_committed(): Instruct AI to commit roadmap deliver + demo create
- _do_cleanup(): Instruct AI to commit worktree/todo removal
**Why:** Operations still needed, but AI should execute, not automation
**Files:** next_machine/core.py (_step_committed, _do_cleanup)

#### 6. Session Auth on Integrate (Bug Fix)
**Status:** Known blocker
**Gap:** telec todo integrate CLI doesn't send X-Caller-Session-ID header
**Result:** API returns 401, CLI surfaces as 500
**Solution:** Inject header from $TMPDIR/teleclaude_session_id in CLI handler
**Priority:** Lower (event path bypasses), but still blocks direct calls
**Files:** tool_commands.py (integrate command handler)

#### 7. Integration Flow Architecture (Confirmed, Documentation)
**Finding:** Event-driven, not queue-based
**Flow:**
1. Orchestrator processes FINALIZE_READY
2. State machine emits deployment.started event
3. IntegrationTriggerCartridge watches event
4. Cartridge: spawn_integrator_session(slug, branch, sha)
5. Cartridge spawns: /next-integrate {slug} --branch {branch} --sha {sha}
6. Integrator: AI-directed delivery bookkeeping (roadmap deliver, demo create, cleanup)
7. Integrator: single squash commit + push main
**Note:** queue.json is vestigial (service.py confirmed file store deprecated). Event-platform is canonical.

#### 8. Finalizer Output Format (Confirmed, No Change Needed)
**Current:** FINALIZE_READY: {slug} (no branch/sha)
**Rationale:** State machine can derive from git. Finalizer stays simple, separation of concerns.
**Recommendation:** Keep current format

#### 9. Delivery Bookkeeping (Confirmed)
**Owner:** Integrator AI (post-merge in /next-integrate)
**Operations (all AI-directed, no auto-commits):**
- telec roadmap deliver {slug}
- telec todo demo create {slug}
- Clean worktree/todo directories
- Commit all: "chore({slug}): delivery and cleanup"
- Push main

### Implementation Order (Priority)
1. mark-phase --cwd (low risk enabler)
2. State machine post-finalize gap: emit_deployment_started (critical blocker)
3. Auto-commits conversion (integrator workflow)
4. Orchestrator role cleanup (post-finalize handler)
5. Session auth fix (lower priority)
6. Policy/documentation updates (state files commit rule)

### Verification Checklist
- [ ] Finalizer: reports FINALIZE_READY with slug only
- [ ] State machine: detects finalize from status
- [ ] State machine: derives branch/sha from worktree git
- [ ] State machine: calls emit_deployment_started() successfully
- [ ] Cartridge: receives event, spawns integrator
- [ ] Integrator: receives /next-integrate with correct args
- [ ] Integrator: performs delivery bookkeeping as AI-directed
- [ ] mark-phase: accepts --cwd, updates correct state.yaml
- [ ] Tests: all pass, no regressions

### Open Questions
- Should /next-finalize output branch/sha? (Recommend: no, let state machine derive)
- Any other places orchestrator might emit events?
- Is queue.json fully deprecated or used in parallel?
