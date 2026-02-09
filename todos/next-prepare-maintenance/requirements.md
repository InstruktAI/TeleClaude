# Requirements: Next Prepare Maintenance Runner

## Goal

Implement a maintenance workflow that continuously assesses and upgrades todo
preparation quality (`requirements.md` + `implementation-plan.md`) and records
auditable outcomes via `dor-report.md` and `state.json`.

## Scope

### In scope

1. Define/ship job spec `docs/project/spec/jobs/next-prepare.md`.
2. Add executable maintenance routine for active todo folders.
3. Assess quality using a deterministic DOR scoring model (`1..10`).
4. Improve weak preparation docs in-place when safe.
5. Persist per-todo report + state metadata.
6. Skip already-good todos using freshness-aware criteria.

### Out of scope

- Implementing product features from todos.
- Modifying delivered/icebox items.
- Re-prioritizing roadmap order as part of job runtime.
- Solving unknown architecture decisions by guessing.

## Functional requirements

### FR1: Target selection

- Scan `todos/` for active todo folders.
- Exclude slugs present in `todos/icebox.md` and `todos/delivered.md`.
- Ignore non-todo files (`roadmap.md`, `dependencies.json`, etc.).

### FR2: Required artifact assessment

- Evaluate `requirements.md` and `implementation-plan.md` for readiness quality.
- Treat `input.md` as optional context.
- If either required artifact is missing, generate it using existing repo context.

### FR3: DOR scoring and verdict

- Score each todo on `1..10`.
- Use thresholds:
  - target: `8`
  - human review threshold: `7`
- Set verdict:
  - `pass` for score >= 8
  - `needs_work` for score < 8 and improved safely
  - `needs_human_review` for score < 7 when safe improvement is exhausted

### FR4: Autonomous improvement

- Improve docs when gaps are concrete and grounded.
- Do not invent behavior or architecture outside known context.
- Stop and flag `needs_human_review` when uncertainty becomes blocking.

### FR5: DOR report output

- Write `todos/{slug}/dor-report.md` after each assessment.
- Report must include:
  - score + verdict
  - edits performed
  - remaining gaps
  - stop reason when applicable
  - specific human decisions needed

### FR6: state.json writeback

- Write/update `state.json.dor` with:
  - `last_assessed_at`
  - `score`
  - `status`
  - `schema_version`
  - `blockers`
  - `actions_taken`

### FR7: Freshness-aware skip

- Skip processing if all are true:
  1. `dor-report.md` exists
  2. report newer than `requirements.md` and `implementation-plan.md`
  3. `state.json.dor.schema_version` matches current schema
  4. `state.json.dor.status == "pass"`

## Non-functional requirements

1. Deterministic output format for machine and human readability.
2. Idempotent reruns when nothing changed.
3. No destructive operations on unrelated files.
4. Clear audit trail in every touched todo.

## Acceptance criteria

1. New job spec exists at `docs/project/spec/jobs/next-prepare.md`.
2. Routine can process a batch of active todos and produce DOR reports.
3. state.json quality metadata is written consistently.
4. Freshness skip avoids unnecessary rewrites.
5. At least one intentionally weak todo is improved and rescored.
6. At least one ambiguous todo is flagged `needs_human_review` with explicit blockers.
