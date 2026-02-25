# REVIEW FINDINGS: unified-client-adapter-pipeline

## Critical

- None.

## Important

- Demo verification loops can produce false-positive success and mask missing child artifacts or DOR fields.  
  Confidence: 99%  
  Evidence: [demos/unified-client-adapter-pipeline/demo.md](demos/unified-client-adapter-pipeline/demo.md):10 and [demos/unified-client-adapter-pipeline/demo.md](demos/unified-client-adapter-pipeline/demo.md):25 iterate checks without `set -e` or per-iteration failure propagation. Concrete trace with `missing-slug` first and a valid slug last still exits `0`, so the command can pass despite earlier failures.  
  Why this matters: Build gate evidence can pass while R3/R4 preconditions are violated, weakening readiness guarantees.  
  Suggested fix: Make each loop fail-fast (`... || exit 1`), or enable strict mode (`set -euo pipefail`) around these validation blocks.

- Child readiness snapshot timestamp is internally inconsistent with included child evidence.  
  Confidence: 95%  
  Evidence: [todos/unified-client-adapter-pipeline/dor-report.md](todos/unified-client-adapter-pipeline/dor-report.md):29 labels snapshot time `2026-02-25T04:24:29Z`, but [todos/unified-client-adapter-pipeline/dor-report.md](todos/unified-client-adapter-pipeline/dor-report.md):35 includes child `last_assessed_at=2026-02-25T12:00:00Z` (later than the claimed snapshot instant).  
  Why this matters: DOR audit trail becomes time-incoherent and reduces trust in readiness evidence.  
  Suggested fix: Regenerate the snapshot from current child states at one consistent timestamp, or correct the snapshot header to reflect the actual extraction time.

## Suggestions

- None.

## Fixes Applied

1. Issue: Demo verification loops could mask early failures and still return success.
   Fix: Added per-iteration fail-fast guards (`|| { ...; exit 1; }`) in both parent demo artifacts so missing child artifacts or DOR metadata immediately fail execution.
   Commit: `e393ecd6c44c754564f0ef123b6031fd0c36f0e6`

2. Issue: Child readiness snapshot timestamp coherence.
   Fix: Reintroduced the parent DOR child snapshot with an explicit consistency basis (`snapshot_consistent_as_of` = max child `dor.last_assessed_at`) and refreshed child evidence lines.
   Commit: `0d911b479cedea26bc833c170636477d9bcd19d9`

## Paradigm-Fit Assessment

- Data flow: Reviewed as artifact-only orchestration updates; no inline runtime-path hacks or adapter/core boundary violations introduced.
- Component reuse: No copy-paste runtime implementation introduced; changes remain in parent orchestration artifacts and demo validation instructions.
- Pattern consistency: Parent remains umbrella-only and child ownership stays aligned with roadmap decomposition.

## Manual Verification Evidence

- Executed roadmap/dependency and child-artifact checks against `todos/roadmap.yaml` and all six UCAP child slugs.
- Executed concrete shell traces demonstrating loop exit-status behavior with failing first iteration and successful last iteration (`exit=0` repro).
- Verified parent runtime-scope guard query (`teleclaude/` scan in parent implementation plan) returns no matches.

Verdict: REQUEST CHANGES
