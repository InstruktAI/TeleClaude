---
description: 'Gate phase job for next-prepare. Runs formal DOR validation and is the only phase allowed to authorize readiness.'
id: 'project/spec/jobs/next-prepare-gate'
scope: 'project'
type: 'spec'
---

# Next Prepare Gate — Spec

## Required reads

- @~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
- @~/.teleclaude/docs/software-development/procedure/maintenance/next-prepare.md
- @~/.teleclaude/docs/software-development/procedure/maintenance/next-prepare-gate.md

## What it is

`next-prepare-gate` performs formal Definition-of-Ready validation over draft artifacts.
It must run in a separate worker session from draft.

## Canonical fields

- `scope`: explicit slug or batch mode; handles only slugs with preparation artifacts present.
- `focus`: validation and minimal factual tightening.
- `outputs` per processed slug: updated `dor-report.md` with gate verdict; updated `state.json.dor` with final gate status and score; optional minimal refinements to requirements/plan.
- `phase_authority`: gate sets `dor.score` in `state.json`; readiness is derived from `dor.score >= 8`. Only this variant may authorize phase transition to `ready`.
