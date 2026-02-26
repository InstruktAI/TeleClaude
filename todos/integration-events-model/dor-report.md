# DOR Report (Gate): integration-events-model

## Gate Summary

Formal DOR gate for Step 2 of the integration rollout. Draft artifacts were
validated against the codebase and the integration-orchestrator spec. Both draft
blockers are resolved with evidence; no external decisions remain.

## Gate Assessment

1. **Intent & success: PASS**
   - Requirements explicitly state what/why: durable event model and readiness
     projection for canonical signals (`review_approved`, `finalize_ready`,
     `branch_pushed`).
   - Success criteria are concrete, testable, and traceable to functional
     requirements FR1-FR5.

2. **Scope & size: PASS**
   - 3 phases, 7 tasks. Core additions: 1 migration, 1 new module
     (`integration_events.py`), additions to 4 existing files.
   - Queue/lease runtime and cutover authority are explicitly deferred to
     `integrator-shadow-mode` and `integrator-cutover`.
   - Fits a single AI session.

3. **Verification: PASS**
   - Plan includes targeted unit tests for event validation, projection state
     transitions, supersession, idempotency, and finalize-flow sequencing.
   - Full suite (`make test`, `make lint`) as exit gate.

4. **Approach known: PASS**
   - Migration pattern well-established (23 existing migrations, next is 024).
   - `review_approved` seam: `mark_phase()` in `core.py` line 498, called by
     `/todos/mark-phase` route in `todo_routes.py` line 147.
   - `finalize_ready` seam: FINALIZE_READY consumption in orchestrator template
     at `core.py` line 125-131, with lock verification.
   - `branch_pushed` seam: finalize-apply step 10 (`git push origin main`) at
     `core.py` line 165. See resolved blocker 1 below.
   - No architectural unknowns remain.

5. **Research complete: PASS (auto)**
   - No third-party libraries or integrations introduced.

6. **Dependencies & preconditions: PASS**
   - `integration-safety-gates` is delivered and encoded as `after:` in roadmap.
   - Branch/sha metadata is available at all emission points (verified via
     template variables and function signatures).
   - Canonical `teleclaude.db` via `db.py` async manager.

7. **Integration safety: PASS**
   - Additive only: new tables, new module, additions to existing code paths.
   - Existing finalize safety gate behavior preserved (plan explicitly states
     "Keep finalize safety-gate ordering intact").
   - Does not enable singleton integrator execution.

8. **Tooling impact: PASS (auto)**
   - No scaffolding or tooling workflow changes.

## Plan-to-Requirement Fidelity

| Task  | Requirement(s) | Verdict    |
| ----- | -------------- | ---------- |
| 1.1   | FR1, FR4       | Consistent |
| 1.2   | FR3, FR4       | Consistent |
| 2.1   | FR2, FR5       | Consistent |
| 2.2   | FR2, FR5       | Consistent |
| 3.1-2 | SC all         | Consistent |

No contradictions detected between plan tasks and requirements.

## Resolved Blockers

### 1. `branch_pushed` emission source

**Resolution:** Wire at finalize-apply step 10 (`git push origin main`), which
is the point where the candidate sha becomes reachable on remote. In the current
flow, the orchestrator merges feature into main locally then pushes main — the
sha is now on remote via main. Record `branch` as the feature branch name,
`sha` as the merge-base sha, `remote` as `origin`.

When `integrator-shadow-mode` introduces feature-branch-to-remote push (the
integrator needs `origin/<branch>`), the emission point shifts to the new push
step. This todo records the event at the existing push seam; shadow-mode
adjusts the seam.

### 2. Event write surface

**Resolution:** Two patterns, matching existing codebase conventions:

- **`review_approved`**: Direct core call inside `mark_phase()` or the
  `/todos/mark-phase` API handler (code-level seam, no agent instruction
  change needed).
- **`finalize_ready` and `branch_pushed`**: Add a thin API endpoint
  (e.g., `/todos/record-integration-event`) and add a step to the finalize
  orchestrator template instructions to call it after evidence verification
  and after push. This follows the existing pattern where orchestrator
  agents execute template instructions that include API/CLI calls.

## Assumptions (validated)

1. `finalize_ready` and `branch_pushed` recording wires at deterministic
   orchestration points without redesigning the runtime. **Confirmed**: seams
   identified at template step 4 (FINALIZE_READY consumption) and step 10
   (push).
2. Candidate branch/sha metadata is available at emission time. **Confirmed**:
   template variables `{args}` carry slug; branch/sha are accessible from git
   state at the worktree and main repo.
3. Event persistence uses canonical `teleclaude.db`. **Confirmed**: `db.py`
   async manager pattern established.

## Gate Verdict

**Score: 8 / 10** | **Status: PASS**

All DOR gates satisfied. Both draft blockers resolved with codebase evidence.
Ready for implementation planning and scheduling.
