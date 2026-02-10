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
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-draft.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-gate.md

## Job contract

This spec defines the stable contract for the `next-prepare` job family.
Execution flow and state handling live in maintenance procedures.

The job family has two explicit variants:

- `next-prepare-draft`
- `next-prepare-gate`

Both support two scopes:

- `slug` provided: process one specific todo.
- no `slug`: iterate active todos needing that phase.

Hard rule: draft and gate must never run in the same worker session.

## Scope contract

- Processes active todo slugs under `todos/`
- Excludes slugs listed in `todos/icebox.md` and `todos/delivered.md`
- Runs idempotently
- Improves preparation artifacts only (not feature implementation)
- Draft variant handles artifact creation/refinement states.
- Gate variant handles formal DOR validation of draft artifacts.

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
exist, roadmap state is pending `[ ]`, and `state.json.dor.status == "pass"`,
transition to ready `[.]`.

Only `next-prepare-gate` may authorize this transition.

## Ownership boundary

- This spec owns the **what** (job inputs/outputs/contracts).
- The maintenance procedure owns the **how** (ordering, state transitions, skip rules, recovery).
