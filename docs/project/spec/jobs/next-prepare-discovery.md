---
description: 'Discovery phase job for next-prepare. Produces grounded requirements from input using solo or triangulated discovery.'
id: 'project/spec/jobs/next-prepare-discovery'
scope: 'project'
type: 'spec'
---

# Next Prepare Discovery — Spec

## Required reads

- @~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
- @~/.teleclaude/docs/software-development/procedure/maintenance/next-prepare.md
- @~/.teleclaude/docs/software-development/procedure/maintenance/next-prepare-discovery.md

## What it is

`next-prepare-discovery` owns the requirements phase of prepare. It turns `input.md`
into grounded `requirements.md`. It may work solo or bring in a complementary partner
when a second perspective is needed, but both paths produce the same artifact.

## Canonical fields

- `scope`: explicit slug or batch mode over active slugs.
- `inputs`: active todo slugs with `input.md`; optional prior `requirements-review-findings.md`.
- `outputs` per processed slug: `requirements.md` and any related grounding metadata in `state.yaml`.
- `phase_constraint`: must not write `implementation-plan.md`, perform todo breakdown, or promote readiness.
