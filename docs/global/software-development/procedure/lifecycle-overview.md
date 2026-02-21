---
description: 'Deterministic software development lifecycle with prepare, build, review, fix, finalize, demo, and maintenance phases. Serial workflow managed by Orchestrator.'
id: 'software-development/procedure/lifecycle-overview'
scope: 'domain'
type: 'procedure'
---

# Lifecycle Overview — Procedure

## Goal

The software development lifecycle in this organization follows a deterministic, serial workflow managed by the Orchestrator.

1. Prepare — define scope, requirements, and plan
2. Build — implement the plan with tests and commits
3. Review — validate against requirements and standards
4. Fix — address review findings
5. Finalize — merge and deliver
6. Demo — celebrate delivery with a visual presentation
7. Maintenance — infra/dependency/security upkeep

### 1. Prepare

**Output:** `requirements.md`, `implementation-plan.md`
**Responsibility:** Architect

Analyze input, clarify requirements, break down work into single-session todos. Assess readiness using Definition of Ready criteria. If too large, split into smaller todos with dependency tracking.

### 2. Build

**Output:** Code changes, tests, commits
**Responsibility:** Builder

Execute implementation plan task-by-task. Write code, tests, commit after each task. May create `deferrals.md` for genuinely out-of-scope work. Quality gates run before committing.

### 3. Review

**Output:** `review-findings.md`, verdict
**Responsibility:** Reviewer

Evaluate work against requirements and standards. Run parallel review lanes (code quality, tests, error handling, types, comments, security). Deliver verdict: APPROVE or REQUEST CHANGES.

### 4. Fix (if needed)

**Output:** Code changes addressing findings
**Responsibility:** Builder

Address review findings. Re-commit. Workflow returns to Review phase.

Review/fix loops are capped by `max_review_rounds` (default `3`). At the cap, orchestrator owns pragmatic closure: approve with documented follow-up for non-critical residual items, and escalate only when unresolved critical risk remains.

### 5. Finalize

**Output:** Merge, log delivery, cleanup
**Responsibility:** Orchestrator

Merge approved work, update delivered log, remove todo folder, clean up worktree.

### 6. Demo

**Output:** `demos/{NNN}-{slug}/` with `snapshot.json` and `demo.sh`
**Responsibility:** Orchestrator

Triggered automatically after finalize, before cleanup. Captures delivery metrics and narrative into a durable demo artifact, presents a visual celebration via widget, and commits the result. Render scripts are gated by semver — breaking major version bumps disable stale demos automatically.

### 7. Maintenance

**Output:** Infra/dependency/security upkeep
**Responsibility:** Orchestrator

Maintenance covers dependency updates, security patches, and operational upkeep. Procedures are defined separately.

- **Serial execution**: One phase runs, completes, then the next begins
- **Deterministic handoffs**: Every step ends cleanly before the next begins
- **No micromanagement**: Orchestrator dispatches and monitors; workers implement autonomously
- **Quality gates**: Pre-commit hooks enforce standards; review validates completeness

Work state lives in `todos/{slug}/state.json` and records:

- `build`: `pending` | `complete`
- `review`: `pending` | `approved` | `changes_requested`
- `deferrals_processed`: boolean

## Preconditions

- Work item exists in `todos/roadmap.yaml`.
- `requirements.md` and `implementation-plan.md` are present.

## Steps

1. Run preparation to validate requirements and plan.
2. Execute build phase to implement changes.
3. Run review phase; address findings in fix phase if needed.
4. Finalize by merging, logging delivery, and cleaning up.

## Outputs

- Updated `state.json` reflecting phase progression.
- Work item marked delivered when complete.

## Recovery

- If blocked, record deferrals and reschedule the work item.
