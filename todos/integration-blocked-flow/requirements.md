# Requirements: integration-blocked-flow

## Problem

`docs/project/spec/integration-orchestrator.md` defines `integration_blocked`
as a canonical integration outcome, but the implementation contract for blocked
cases is incomplete. Today, merge conflicts can stop canonical integration
without a deterministic follow-up todo, without consistent evidence capture, and
without a clear resume path for operators.

## Intended Outcome

When integration cannot proceed for a candidate `(slug, branch, sha)`, the
system must produce a deterministic blocked-flow result that is:

1. auditable (`integration_blocked` evidence is persisted and queryable),
2. actionable (a follow-up todo is created or reused with unblock context),
3. resumable (operator receives explicit next commands to continue delivery).

This is the Step 5 rollout slice after `integrator-cutover`.

## Scope

### In scope

1. **R1 - Canonical blocked outcome contract**
   Define required blocked payload fields and reason taxonomy for
   `integration_blocked`.
2. **R2 - Follow-up todo creation/reuse**
   Auto-create or reuse a deterministic follow-up todo tied to the blocked
   candidate.
3. **R3 - Idempotent replay behavior**
   Repeated blocked detections for the same candidate must not spam duplicate
   follow-up todos.
4. **R4 - Resume UX contract**
   Return explicit operator guidance (what failed, where evidence is, and
   exactly how to resume).
5. **R5 - Dependency/state safety**
   Keep canonical `main` unchanged on blocked outcomes and maintain queue/item
   state as blocked until remediation.
6. **R6 - Observability**
   Emit grep-friendly logs and persist enough evidence to debug and audit blocked
   outcomes later.
7. **R7 - Verification coverage**
   Add tests for blocked payload, todo creation/reuse, resume guidance, and
   no-partial-main mutation guarantees.

### Out of scope

1. Automatically resolving merge conflicts.
2. Redefining readiness signals (`review_approved`, `finalize_ready`,
   `branch_pushed`) or lease semantics.
3. Integrator authority cutover decisions (owned by `integrator-cutover`).
4. New third-party services, queues, or notification vendors.

## Functional Requirements

### FR1: Integration Blocked Payload

1. The system MUST emit/persist a blocked record keyed to candidate
   `(slug, branch, sha)`.
2. The blocked record MUST include at least:
   `slug`, `branch`, `sha`, `reason`, `blocked_at`, and evidence pointers.
3. For merge-conflict blocks, evidence MUST include deterministic conflict file
   paths (when available) and context needed for follow-up remediation.

### FR2: Follow-up Todo Materialization

1. On first blocked outcome for a candidate, the system MUST create a follow-up
   todo scaffold in `todos/` and register it in `todos/roadmap.yaml`.
2. The follow-up artifact MUST include source linkage to the blocked candidate
   (`slug`, `branch`, `sha`) and unblock intent in `input.md` (or equivalent).
3. If follow-up creation fails, blocked evidence MUST still be persisted and the
   operator MUST receive fallback manual instructions.

### FR3: Idempotency and Deduplication

1. Replaying the same blocked candidate MUST reuse the existing follow-up todo
   instead of creating duplicates.
2. Evidence updates for replays MUST append/update auditable history without
   losing earlier records.

### FR4: Resume UX

1. The blocked output shown to the operator MUST include:
   - blocked reason,
   - follow-up slug,
   - exact commands to continue work and resume integration.
2. Resume messaging MUST be deterministic and consistent across repeated blocked
   events for the same candidate.

### FR5: Integration Safety

1. Blocked outcomes MUST never push partial integration to canonical `main`.
2. Queue/candidate status MUST remain explicitly blocked until follow-up
   remediation is complete and integration is retried.

### FR6: Observability and Auditability

1. Logs MUST include candidate identity plus follow-up slug for grep-based
   operations.
2. Persistent blocked records MUST be queryable for post-incident analysis.

## Success Criteria

- [ ] A deterministic blocked record exists for each `integration_blocked` outcome.
- [ ] First blocked detection auto-creates a follow-up todo with unblock context.
- [ ] Repeated blocked detections reuse the same follow-up todo (no duplicate spam).
- [ ] Operator output includes explicit resume commands and follow-up location.
- [ ] No canonical `main` mutation occurs on blocked outcomes.
- [ ] Targeted tests cover payload shape, deduplication, follow-up creation, and
      resume guidance.
- [ ] Log-based operational checks can retrieve blocked outcomes by candidate or
      follow-up slug.

## Verification Path

1. Unit tests for blocked payload validation and idempotent follow-up todo
   creation/reuse.
2. Unit/integration tests for blocked operator messaging and resume command
   contract.
3. Regression checks proving blocked flow does not mutate canonical `main`.
4. Operational log checks via:
   `instrukt-ai-logs teleclaude --since <window> --grep "integration_blocked|follow_up_slug"`.

## Dependencies and Preconditions

1. `integrator-cutover` must expose the canonical integration-apply seam that
   emits blocked outcomes.
2. Existing todo scaffolding and roadmap mutation primitives must remain
   available (`teleclaude/todo_scaffold.py`, roadmap helpers).
3. Persistence must use canonical `teleclaude.db`
   (`project/policy/single-database`).

## Integration Safety

1. Delivery is incremental and additive: blocked-flow logic can be enabled
   without changing non-blocked successful integration semantics.
2. Rollback/containment is explicit: disable blocked follow-up creation path,
   keep recorded evidence, and preserve existing finalize safety behavior.

## Constraints

1. Maintain adapter boundaries (`project/policy/adapter-boundaries`).
2. Do not introduce third-party dependencies.
3. Reuse canonical todo scaffolding patterns instead of ad-hoc file creation.
4. Preserve daemon availability expectations (`project/policy/daemon-availability`).

## Risks

1. **Follow-up spam risk**: duplicate blocked detections could create too many
   todos if dedupe keys are weak.
2. **Resume ambiguity risk**: unclear next commands can stall operators.
3. **Evidence drift risk**: blocked records and todo context may diverge if
   update paths are inconsistent.

## Research

No third-party tooling or integrations are introduced. Research gate is
automatically satisfied.
