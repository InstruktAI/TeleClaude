---
description: 'Draft phase job for next-prepare. Builds or refines todo preparation artifacts without final readiness decisions.'
id: 'project/spec/jobs/next-prepare-draft'
scope: 'project'
type: 'spec'
---

# Next Prepare Draft — Spec

## Required reads

- @~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-draft.md

## Job contract

`next-prepare-draft` creates and refines preparation artifacts.
It must not perform final gate decisions or readiness promotion.

## Scope contract

- Handles missing or weak prep artifacts for active slugs.
- Supports explicit slug or batch mode.
- May process `input.md` when present.

## Output contract

Per processed slug:

- `requirements.md`
- `implementation-plan.md`
- `dor-report.md` (draft analysis)
- `state.json.dor` (draft metadata)

## Roadmap contract

- Must not transition roadmap `[ ]` to `[.]`.
- Leaves final readiness decision to `next-prepare-gate`.
