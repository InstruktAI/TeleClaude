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

## What it is

`next-prepare-draft` creates and refines preparation artifacts.
It must not perform final gate decisions or readiness promotion.

## Canonical fields

- `scope`: explicit slug or batch mode over active slugs.
- `inputs`: active todo slugs; optional `input.md` per slug.
- `outputs` per processed slug: `requirements.md`, `implementation-plan.md`, `dor-report.md` (draft analysis), `state.json.dor` (draft metadata).
- `phase_constraint`: must not transition item phase from `pending` to `ready` in `state.json`; leaves final readiness decision to `next-prepare-gate`.
