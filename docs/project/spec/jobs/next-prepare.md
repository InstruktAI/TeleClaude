---
description: 'Maintenance job that continuously improves todo readiness by assessing and refining requirements and implementation plans.'
id: 'project/spec/jobs/next-prepare'
scope: 'project'
type: 'spec'
---

# Next Prepare — Spec

## Required reads

- @~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md

## What it is

Defines a maintenance runner job that audits todo preparation quality and improves
it in-place. The job focuses on `requirements.md` and `implementation-plan.md`.
`input.md` is optional context and may be a brain dump.

This is not a feature build job. It is a backlog-quality job.
Detailed state handling is defined in `docs/global/general/procedure/maintenance/next-prepare.md`.

## Canonical fields

### Schedule

Configured in `teleclaude.yml`:

```yaml
jobs:
  next_prepare:
    schedule: weekly
    preferred_weekday: 0
    preferred_hour: 7
    type: agent
    job: next-prepare
    agent: claude
    thinking_mode: med
```

### Scope

- Target: active todo folders under `todos/`
- Exclude: items listed in `todos/icebox.md` and `todos/delivered.md`
- Processing model: idempotent batch pass over active slugs
- Required outputs per active todo:
  - `requirements.md` (exists and quality-checked)
  - `implementation-plan.md` (exists and quality-checked)
  - `dor-report.md` (analysis + actions + remaining blockers)
  - `state.json` updated with DOR quality status

### Use case states

The execution procedure must handle different starting states per slug:

1. `input.md` only (brain dump): synthesize `requirements.md` and `implementation-plan.md`.
2. `requirements.md` only: generate `implementation-plan.md`.
3. `implementation-plan.md` only: reconstruct `requirements.md`, then reconcile plan.
4. both exist but stale or weak: refine both and rescore.
5. both exist and pass with fresh `dor-report.md`: skip.

### Quality model

- Score range: `1..10`
- Target score: `8`
- Human review threshold: `7`

`state.json` writeback contract:

```json
{
  "dor": {
    "last_assessed_at": "2026-02-09T17:00:00Z",
    "score": 8,
    "status": "pass",
    "schema_version": 1,
    "blockers": [],
    "actions_taken": {
      "requirements_updated": true,
      "implementation_plan_updated": true
    }
  }
}
```

`dor.status` values:

- `pass`: score >= 8
- `needs_work`: score < 8 but improved autonomously
- `needs_human_review`: score < 7 and cannot be improved safely

### Freshness rules

Skip a todo only when all are true:

1. `dor-report.md` exists
2. report timestamp is newer than `requirements.md` and `implementation-plan.md`
3. `state.json.dor.schema_version` matches current scoring schema
4. `dor.status == "pass"`

Otherwise re-run assessment.

### Autonomy boundaries

The job may:

- tighten unclear requirements,
- fill missing verification criteria,
- rewrite plans to concrete file/task/verification sequences,
- reduce ambiguity and stale references.

The job must not:

- invent new product behavior not implied by existing context,
- make architectural changes unrelated to preparation quality,
- edit delivered/icebox items,
- force a fake high score by adding speculative content.

If uncertainty crosses safe bounds, it must stop and mark
`needs_human_review` with explicit blockers.

### DOR report format

`todos/{slug}/dor-report.md`:

```markdown
# DOR Report — {slug}

## Verdict

- score: 7/10
- status: needs_human_review

## What changed

- Updated requirements.md: clarified success criteria and role constraints
- Updated implementation-plan.md: added verification steps and risk section

## Remaining gaps

- Missing architectural decision on auth boundary for endpoint X
- Dependency ambiguity with slug Y

## Why execution stopped

- Further edits would require inventing behavior not grounded in existing docs/code

## Human decisions needed

1. Confirm auth policy for endpoint X
2. Confirm dependency order between slugs Y and Z
```

## Allowed values

- Agents: `claude`, `codex`, `gemini` (project config)
- `thinking_mode`: `fast`, `med`, `slow`
- `dor.score`: integer 1 to 10
- `dor.status`: `pass`, `needs_work`, `needs_human_review`
- `dor.schema_version`: positive integer

## Known caveats

- This job improves preparation artifacts, not implementation correctness.
- Highly ambiguous todos may remain below threshold by design and require human decisions.
- Score consistency depends on a stable scoring rubric; bump `schema_version` when rubric changes.
- Procedure changes must keep this spec contract stable (artifact names, score range, thresholds, and state keys).
