# prepare-state-machine — Input

Rewrite the next_prepare() function in teleclaude/core/next_machine/core.py as a proper state machine with durable checkpoints, modeled on the integration state machine pattern.

The current implementation is a linear if/else chain that checks artifact existence. It needs to become a deterministic state machine where each call reads durable state from state.yaml, executes the next step, and returns structured instructions.

Key changes:

1. PreparePhase enum: INPUT_ASSESSMENT, TRIANGULATION, REQUIREMENTS_REVIEW, PLAN_DRAFTING, PLAN_REVIEW, GATE, GROUNDING_CHECK, RE_GROUNDING, PREPARED, BLOCKED

2. Remove the hitl parameter entirely. The machine always returns tool-call instructions for the orchestrator. Human interaction is via next-refine-input only.

3. State lives in state.yaml grounding section:
   - grounding.valid (bool)
   - grounding.base_sha (main HEAD when last grounded)
   - grounding.input_digest (hash of input.md)
   - grounding.referenced_paths (file paths from implementation plan)
   - grounding.last_grounded_at (ISO8601)
   - grounding.invalidated_at (ISO8601 or null)
   - grounding.invalidation_reason (files_changed, input_updated, policy_updated, or null)
   - requirements_review.verdict (approve | needs_work)
   - requirements_review.reviewed_at (ISO8601)
   - requirements_review.findings_count (int)
   - plan_review.verdict (approve | needs_work)
   - plan_review.reviewed_at (ISO8601)
   - plan_review.findings_count (int)

4. Phase transitions with events:
   - input.md exists + no requirements.md → TRIANGULATION (emit prepare.triangulation_started)
   - requirements.md written → REQUIREMENTS_REVIEW (dispatch next-review-requirements)
   - requirements_review.verdict == approve → PLAN_DRAFTING (emit prepare.requirements_approved, dispatch next-prepare-draft)
   - requirements_review.verdict == needs_work → TRIANGULATION (re-dispatch with findings)
   - plan written → PLAN_REVIEW (dispatch next-review-plan)
   - plan_review.verdict == approve → GATE (emit prepare.plan_approved, dispatch next-prepare-gate)
   - plan_review.verdict == needs_work → PLAN_DRAFTING (re-dispatch with findings)
   - gate passed → GROUNDING_CHECK (mechanical freshness: compare base_sha, input_digest, referenced_paths)
   - stale → RE_GROUNDING (dispatch agent with diff, emit prepare.regrounded)
   - fresh → PREPARED (emit prepare.completed)

5. Review commands (agent-driven, not mechanical):
   - next-review-requirements: reviews requirements.md against quality standard (completeness, testability, grounding, review-awareness, no implementation leakage, inference transparency)
   - next-review-plan: reviews implementation-plan.md against policies, DoD gates, and review lane expectations (requirement coverage, rationale presence, verification completeness, lane anticipation, policy compliance, referenced paths)
   - Each writes verdict and findings to state.yaml and findings file
   - needs_work verdict loops back to the producing phase with findings attached

6. New CLI flag: telec todo prepare --invalidate-check --changed-paths foo.py,bar.py
   - Checks ALL active todos (no slug)
   - For each: compare changed-paths against grounding.referenced_paths
   - If overlap: set grounding.valid=false, invalidated_at=now, invalidation_reason=files_changed
   - Emit prepare.grounding_invalidated event for each invalidated slug
   - Pure automation, no agent, milliseconds

7. Pre-build freshness gate: before next_work dispatches a builder, call next_prepare as pre-flight. If stale, re-ground first.

8. Event emission: use the same EventProducer pattern as integration state machine. Emit at each phase transition with slug in payload.

Reference the integration state machine at teleclaude/core/integration/state_machine.py for the checkpoint pattern, phase enum, and event emission approach.

The procedures and commands that govern this are:
- general/procedure/maintenance/next-prepare.md (state machine driver)
- general/procedure/maintenance/next-prepare-discovery.md (triangulation — two-agent requirements derivation)
- general/procedure/maintenance/next-prepare-draft.md (plan drafting)
- general/procedure/maintenance/next-prepare-gate.md (DOR gate)
- software-development/procedure/lifecycle/prepare.md (architecture overview)
- software-development/procedure/lifecycle/review-requirements.md (requirements quality review)
- software-development/procedure/lifecycle/review-plan.md (plan quality review)
- software-development/procedure/lifecycle/refine-input.md (human intent capture)

Commands:
- next-prepare (orchestrator — state machine driver)
- next-prepare-draft (worker — plan drafting)
- next-prepare-gate (worker — DOR gate)
- next-review-requirements (worker — requirements review)
- next-review-plan (worker — plan review)
- next-refine-input (worker — human intent capture)

Events are registered in teleclaude_events/schemas/software_development.py under the Prepare lifecycle events section.
