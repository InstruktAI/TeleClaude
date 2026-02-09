---
description: 'Maintenance job that continuously improves todo readiness by assessing and refining requirements and implementation plans.'
id: 'project/spec/jobs/next-prepare'
scope: 'project'
type: 'spec'
---

# Next Prepare — Spec

## Required reads

- @~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md

## Job contract

This spec defines only the stable contract of the `next-prepare` job.
Execution flow and state handling live in:
`docs/global/general/procedure/maintenance/next-prepare.md`.

The same process supports two scopes:

- `slug` provided: prepare one specific todo.
- no `slug`: iterate active todos that still need preparation work.

## Configuration surface

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

## Scope contract

- Processes active todo slugs under `todos/`
- Excludes slugs listed in `todos/icebox.md` and `todos/delivered.md`
- Runs idempotently
- Improves preparation artifacts only (not feature implementation)
- Must handle these starting states:
  - `input.md` only
  - `requirements.md` only
  - `implementation-plan.md` only
  - both files present
  - neither file present

## Output contract

Per processed slug, the job may update:

- `requirements.md`
- `implementation-plan.md`
- `dor-report.md`
- `state.json` (`dor` section)

`state.json.dor` contract:

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

Allowed values:

- `dor.score`: integer `1..10`
- `dor.status`: `pass`, `needs_work`, `needs_human_review`
- `dor.schema_version`: positive integer

Threshold constants:

- Target quality: `8`
- Human review required: `< 7`

## Roadmap state contract

For slug-targeted prepare, when both `requirements.md` and `implementation-plan.md`
exist and roadmap state is pending `[ ]`, transition to ready `[.]`.

## Ownership boundary

- This spec owns the **what** (job inputs/outputs/contracts).
- The maintenance procedure owns the **how** (ordering, state transitions, skip rules, recovery).
