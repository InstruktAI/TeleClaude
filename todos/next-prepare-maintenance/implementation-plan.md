# Implementation Plan: Next Prepare Maintenance Runner

## Objective

Deliver a maintenance routine that continuously improves todo preparation quality
and records DOR analysis results.

## Task sequence

### Task 1: Job spec and scoring contract

Files:

- `docs/project/spec/jobs/next-prepare.md`

Work:

1. Define job scope, thresholds, and output artifacts.
2. Lock scoring schema (`schema_version = 1`).
3. Define freshness-aware skip logic and autonomy boundaries.

Verification:

- Spec includes required sections and concrete report/state formats.

### Task 2: Todo target discovery and filtering

Files:

- job implementation entrypoint (new or existing maintenance runner module)

Work:

1. Enumerate todo directories under `todos/`.
2. Parse `todos/icebox.md` and `todos/delivered.md` slug sets.
3. Build active target list (exclude parked/completed/system files).

Verification:

- Dry-run prints expected active slugs only.

### Task 3: DOR assessor

Files:

- maintenance assessor module (new)

Work:

1. Evaluate `requirements.md` quality (clarity, testability, constraints, dependencies).
2. Evaluate `implementation-plan.md` quality (concrete edits, verification, risks).
3. Generate score (`1..10`) + verdict (`pass|needs_work|needs_decision`).

Verification:

- Unit tests for scoring thresholds and verdict mapping.

### Task 4: Safe improver

Files:

- maintenance improver module (new)

Work:

1. Fill missing preparation files.
2. Tighten weak sections without inventing behavior.
3. Stop at uncertainty boundary and record blockers.

Verification:

- Fixture todo with missing plan gets generated plan.
- Ambiguous fixture todo remains blocked with explicit rationale.

### Task 5: Report + state writer

Files:

- maintenance output writer module (new)

Work:

1. Write `todos/{slug}/dor-report.md` in fixed template.
2. Update `todos/{slug}/state.json.dor` fields.
3. Preserve existing unrelated keys in `state.json`.

Verification:

- Report and state are deterministic across repeated runs.

### Task 6: Freshness skip and rerun behavior

Files:

- maintenance orchestrator module

Work:

1. Implement skip criteria from spec.
2. Reprocess only when source artifacts or schema version changed.

Verification:

- Two consecutive runs: second run skips unchanged passing todos.
- Touching `requirements.md` triggers reassessment.

## Risks

1. Over-rewriting human-authored plans -> mitigate with bounded edits and blockers.
2. False confidence from inflated scores -> mitigate with strict rubric and schema versioning.
3. Drift between spec and runtime behavior -> mitigate with integration tests.

## Exit criteria

1. DOR job spec is published and synced.
2. Routine runs on active todos and writes report + score metadata.
3. Skip logic prevents noisy churn.
4. Decision escalations are explicit and actionable.
