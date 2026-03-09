---
description: 'Draft phase job for next-prepare. Builds implementation plans from approved requirements and splits oversized work into child todos when needed.'
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

`next-prepare-draft` turns approved requirements into executable builder planning.
It either writes the implementation plan for an atomic todo or materializes a split
into child todos when planning shows the parent is too large.
It must not perform final gate decisions or readiness promotion.

## Canonical fields

- `scope`: explicit slug or batch mode over active slugs.
- `inputs`: active todo slugs with approved `requirements.md`; optional `input.md` for intent recall.
- outputs per processed slug: atomic case → `implementation-plan.md`, `demo.md`,
  grounded `state.yaml`; split case → child todos, dependency links, updated holder
  `breakdown`.
- `phase_constraint`: must not transition item phase from `pending` to `ready`; leaves final readiness decision to `next-prepare-gate`.
