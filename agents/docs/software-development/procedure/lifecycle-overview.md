---
description:
  Deterministic software development lifecycle with prepare, build, review,
  fix, documentation, finalize, and maintenance phases. Serial workflow managed by Orchestrator.
id: software-development/procedure/lifecycle-overview
scope: domain
type: procedure
---

# Lifecycle Overview

The software development lifecycle in this organization follows a deterministic, serial workflow managed by the Orchestrator.

## Lifecycle Index

1. Prepare — define scope, requirements, and plan
2. Build — implement the plan with tests and commits
3. Review — validate against requirements and standards
4. Fix — address review findings
5. Documentation — sync docstrings and docs
6. Finalize — merge and archive
7. Maintenance — infra/dependency/security upkeep

## Lifecycle Phases

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

### 5. Documentation

**Output:** Updated docstrings and docs
**Responsibility:** Orchestrator

Run docstring synchronization, then snippet synchronization. This phase is part of the work lifecycle and required for Definition of Done.

### 6. Finalize

**Output:** Merge, archive, cleanup
**Responsibility:** Orchestrator

Merge approved work, archive todo folder to `done/`, update delivered log, clean up worktree.

### 7. Maintenance

**Output:** Infra/dependency/security upkeep
**Responsibility:** Orchestrator

Maintenance covers dependency updates, security patches, and operational upkeep. Procedures are defined separately.

## Key Principles

- **Serial execution**: One phase runs, completes, then the next begins
- **Deterministic handoffs**: Every step ends cleanly before the next begins
- **No micromanagement**: Orchestrator dispatches and monitors; workers implement autonomously
- **Quality gates**: Pre-commit hooks enforce standards; review validates completeness

## State Tracking

Work state lives in `todos/{slug}/state.json` and records:

- `build`: `pending` | `complete`
- `review`: `pending` | `approved` | `changes_requested`
- `docstrings`: `pending` | `complete`
- `docs`: `pending` | `complete`
- `deferrals_processed`: boolean
