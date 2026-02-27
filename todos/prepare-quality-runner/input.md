# Next Prepare Maintenance Runner — Input

## Context

We want maintenance automation that keeps todo preparation quality high without
manual babysitting. The current process relies on ad-hoc `next_prepare` passes.
That creates drift and uneven quality across `requirements.md` and
`implementation-plan.md`.

## Objective

Create a maintenance routine (job spec + runnable implementation todo) that:

1. audits active todo quality,
2. improves preparation artifacts in-place when safe,
3. writes `dor-report.md` for each assessed todo,
4. updates `state.json` with a quality score and verdict.

`input.md` is optional context, not a hard prerequisite.

## Expected result

- Every active todo has current, high-quality preparation artifacts.
- Weak todos are either improved above threshold or explicitly flagged for human review.
- The maintenance routine is deterministic, auditable, and safe against hallucinated edits.
