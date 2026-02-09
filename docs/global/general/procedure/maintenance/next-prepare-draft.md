---
id: 'general/procedure/maintenance/next-prepare-draft'
type: 'procedure'
scope: 'global'
description: 'Draft phase for next-prepare. Creates or refines prep artifacts but does not make final readiness decisions.'
---

# Next Prepare Draft — Procedure

## Goal

Produce strong draft preparation artifacts for active todos:

- `requirements.md`
- `implementation-plan.md`
- `dor-report.md` (draft analysis)

This phase is creative and constructive. It improves quality but does not make final readiness decisions.

## Preconditions

1. Job was launched as `next-prepare-draft`.
2. `todos/roadmap.md`, `todos/icebox.md`, and `todos/delivered.md` are readable.
3. Slug is active only if not listed in icebox or delivered.

## Steps

1. Resolve scope:
   - if `slug` provided, process that slug only;
   - else process active slugs that still need prep work.
2. Identify artifact state:
   - State A: only `input.md` present (brain dump);
   - State B: only `requirements.md` present;
   - State C: only `implementation-plan.md` present;
   - State D: both present but weak/stale;
   - State E: neither present.
3. Apply draft generation/refinement:
   - State A: derive requirements, then derive plan;
   - State B: derive plan from requirements (+ `input.md` if present);
   - State C: reconstruct requirements from plan/context, then reconcile plan;
   - State D: tighten requirements first, then tighten plan;
   - State E: create minimal placeholders and capture blockers.
4. Enforce uncertainty boundary:
   - improve structure and clarity;
   - do not invent unsupported behavior;
   - if blocked by uncertainty, stop and record blockers.
5. Write draft outputs per slug:
   - update `requirements.md` and/or `implementation-plan.md`,
   - write `dor-report.md` with explicit assumptions and open questions,
   - update `state.json.dor` with draft assessment fields.
6. Do not change roadmap status in draft phase.

## Outputs

1. Updated preparation artifacts for each processed slug.
2. `todos/{slug}/dor-report.md` with a draft assessment narrative.
3. `todos/{slug}/state.json` with draft DOR metadata.

## Recovery

1. If a slug cannot be safely improved, write blockers in `dor-report.md` and continue.
2. If a file is malformed, preserve it, record issue, continue with other slugs.
