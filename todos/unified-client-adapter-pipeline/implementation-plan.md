# Implementation Plan - unified-client-adapter-pipeline

## Objective

Maintain `unified-client-adapter-pipeline` as a parent orchestration item that governs
child-scope decomposition, dependency integrity, and readiness tracking. No runtime
implementation work is executed under this parent slug.

## Requirement Traceability

- Phase 1 -> R1, R2
- Phase 2 -> R3
- Phase 3 -> R4
- Phase 4 -> R5 and Acceptance Criteria 1-5

## Phase 1 - Parent Scope and Dependency Reconciliation

- [x] Verify parent slug remains umbrella-only in requirements, implementation plan, and demo artifacts.
- [x] Verify UCAP child set and dependency ordering in `todos/roadmap.yaml` match parent requirements.
- [x] Record parent-artifact updates whenever dependency edges or child set change.

### Files (expected)

- `todos/roadmap.yaml`
- `todos/unified-client-adapter-pipeline/requirements.md`
- `todos/unified-client-adapter-pipeline/implementation-plan.md`
- `todos/unified-client-adapter-pipeline/demo.md`

## Phase 2 - Child Preparation Artifact Hygiene

- [x] Confirm each UCAP child slug contains `requirements.md`, `implementation-plan.md`, `dor-report.md`, and `state.yaml`.
- [x] Confirm each child implementation plan traces to that child's requirements.
- [x] Record missing/stale child artifacts as parent DOR blockers.

### Files (expected)

- `todos/ucap-canonical-contract/*`
- `todos/ucap-truthful-session-status/*`
- `todos/ucap-web-adapter-alignment/*`
- `todos/ucap-tui-adapter-alignment/*`
- `todos/ucap-ingress-provisioning-harmonization/*`
- `todos/ucap-cutover-parity-validation/*`

## Phase 3 - Readiness and Dispatch Governance

- [x] Validate each child `state.yaml` has `dor` metadata (`score`, `status`, `last_assessed_at`).
- [x] Preserve dispatch rule: only child slugs with `dor.score >= 8` are ready candidates for build dispatch.
- [x] Keep parent focused on readiness governance; do not convert parent into executable build scope.

### Files (expected)

- `todos/ucap-*/state.yaml`
- `todos/unified-client-adapter-pipeline/dor-report.md`
- `todos/unified-client-adapter-pipeline/state.yaml`

## Phase 4 - Program Readiness Reporting

- [x] Keep parent `dor-report.md` synchronized with current child readiness and dependency state.
- [x] Keep parent demo commands focused on orchestration verification rather than runtime tests.
- [x] Re-run parent gate whenever parent artifacts or UCAP dependency structure changes.

### Files (expected)

- `todos/unified-client-adapter-pipeline/dor-report.md`
- `todos/unified-client-adapter-pipeline/demo.md`
- `todos/unified-client-adapter-pipeline/state.yaml`

## Definition of Done

- [x] Parent artifacts are umbrella-only and aligned with roadmap decomposition.
- [x] Child ownership and dependency order are explicit and consistent.
- [x] Parent DOR can be evaluated without parent runtime implementation tasks.
