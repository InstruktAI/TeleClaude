---
id: 'general/procedure/maintenance/next-prepare-gate'
type: 'procedure'
scope: 'global'
description: 'Gate phase for next-prepare. Performs formal DOR validation and is the only phase allowed to drive readiness decisions.'
---

# Next Prepare Gate — Procedure

## Goal

Run formal Definition-of-Ready validation on prepared artifacts and produce a final gate verdict.

This phase is critical and evidence-driven. It is not a drafting phase.

## Preconditions

1. Job was launched as `next-prepare-gate`.
2. Draft artifacts exist for the target slug:
   - `requirements.md`
   - `implementation-plan.md`
   - `dor-report.md` (draft)
3. Gate worker is separate from the draft worker session.

## Steps

1. Resolve scope:
   - if `slug` provided, gate that slug only;
   - else gate active slugs with draft artifacts and pending gate decision.
2. Validate DOR criteria:
   - intent and outcome clarity,
   - scope atomicity,
   - verification path,
   - dependency correctness,
   - uncertainty and assumptions made explicit.
3. Tighten artifacts with minimal edits when factual gaps exist.
4. Assign final gate result in `state.json.dor`:
   - `score` (`1..10`)
   - `status` (`pass`, `needs_work`, `needs_decision`)
   - `schema_version`
   - `blockers`
   - `actions_taken`
   - `last_assessed_at`
5. Update `dor-report.md` with gate verdict and exact unresolved blockers.
6. Roadmap promotion policy:
   - only gate phase may permit pending `[ ]` to ready `[.]`,
   - only when both required files exist and `state.json.dor.status == "pass"`.

## Outputs

1. Finalized `state.json.dor` gate verdict.
2. Updated `dor-report.md` reflecting gate decision.
3. Ready transition eligibility for roadmap updates.

## Recovery

1. If evidence is insufficient, set `needs_decision` and list required decisions.
2. If contradictions exist between artifacts, mark `needs_work` and describe exact fixes.
