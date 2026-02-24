# Requirements - unified-client-adapter-pipeline

## Problem

The UCAP work has already been split into child todos in `todos/roadmap.yaml`, but this
parent todo still describes end-to-end implementation scope. That mismatch causes readiness
ambiguity and violates Definition of Ready scope atomicity.

## Goal

Define this parent todo as an umbrella/orchestration item only, with no direct runtime
implementation scope. Build work must be owned and executed only by child UCAP todos.

## Dependency

- Parent initiative depends on `transcript-first-output-and-hook-backpressure`.
- Child dependency sequencing is defined in `todos/roadmap.yaml`.

## Canonical Baseline

- `docs/project/design/architecture/agent-activity-streaming-target.md`
- `docs/project/spec/session-output-routing.md`
- `docs/project/policy/adapter-boundaries.md`

## Child Todo Set (Authoritative)

- `ucap-canonical-contract`
- `ucap-truthful-session-status`
- `ucap-web-adapter-alignment`
- `ucap-tui-adapter-alignment`
- `ucap-ingress-provisioning-harmonization`
- `ucap-cutover-parity-validation`

## In Scope

- Keep parent requirements/plan/demo aligned to umbrella-only responsibilities.
- Maintain child decomposition and dependency ordering in `todos/roadmap.yaml`.
- Ensure each child owns executable requirements, implementation plan, and DOR tracking.
- Track readiness progression across child slugs and keep parent artifacts synchronized.

## Out of Scope

- Direct production code changes in `teleclaude/*`.
- Child-level implementation tasks, tests, or cutover execution details.
- New frontend, protocol, or adapter behavior requirements beyond child todo scopes.

## Functional Requirements

### R1. Parent-as-Umbrella Contract

- Parent artifacts must define orchestration scope only.
- Parent implementation plan must not prescribe runtime code changes.

### R2. Dependency Integrity

- Parent artifacts must reflect the child dependency graph in `todos/roadmap.yaml`.
- Any dependency sequence change must be reflected in parent artifacts during the same update.

### R3. Child Artifact Completeness

- Each child slug must maintain:
  - `requirements.md`
  - `implementation-plan.md`
  - `dor-report.md`
  - `state.yaml` with `dor` metadata

### R4. Readiness Governance

- Parent tracks readiness through child `state.yaml.dor` outcomes.
- Child build dispatch eligibility remains gated by DOR (`score >= 8`).

### R5. Program-Level Integration Safety

- Parent defines sequencing and containment expectations only.
- Runtime cutover/rollback behavior is owned by relevant child slugs, especially
  `ucap-cutover-parity-validation`.

## Acceptance Criteria

1. Parent artifacts (`requirements.md`, `implementation-plan.md`, `demo.md`) are umbrella-only.
2. Parent docs and `todos/roadmap.yaml` describe the same UCAP child set and ordering.
3. All UCAP child slugs listed above have prep artifacts and DOR metadata.
4. Parent dispatch guidance is unambiguous: executable build work occurs in child slugs only.
5. Parent DOR can be assessed without requiring parent runtime implementation tasks.

## Risks

- Roadmap/docs drift can reintroduce monolithic scope in the parent slug.
- Child readiness state can become stale if parent orchestration artifacts are not kept current.
