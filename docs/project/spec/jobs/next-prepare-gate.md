---
description: 'Gate phase job for next-prepare. Runs formal DOR validation and is the only phase allowed to authorize readiness.'
id: 'project/spec/jobs/next-prepare-gate'
scope: 'project'
type: 'spec'
---

# Next Prepare Gate — Spec

## Required reads

- @~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-gate.md

## Job contract

`next-prepare-gate` performs formal Definition-of-Ready validation over draft artifacts.
It must run in a separate worker session from draft.

## Scope contract

- Handles only slugs with preparation artifacts present.
- Supports explicit slug or batch mode.
- Focuses on validation and minimal factual tightening.

## Output contract

Per processed slug:

- Updated `dor-report.md` with gate verdict
- Updated `state.json.dor` with final gate status and score
- Optional minimal refinements to requirements/plan when needed for accuracy

## Phase contract

- Gate sets `dor.score` in `state.json`; readiness is derived from `dor.score >= 8`.
