---
id: 'software-development/procedure/maintenance/next-prepare-gate'
type: 'procedure'
scope: 'global'
description: 'Gate phase for next-prepare. Performs formal DOR validation on the complete artifact set and is the only phase allowed to drive readiness decisions.'
---

# Next Prepare Gate — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md

## Goal

Run formal Definition-of-Ready validation on the complete preparation artifact set
(requirements + implementation plan, both individually reviewed and approved) and
produce a final gate verdict.

This phase is critical and evidence-driven. It validates the full artifact set as a
coherent whole — not the individual artifacts (those are reviewed in earlier phases).

## Preconditions

1. `todos/{slug}/requirements.md` exists and is approved.
2. `todos/{slug}/implementation-plan.md` exists and is approved.
3. Gate worker is separate from draft/discovery workers.

## Steps

### 1. Cross-artifact validation

Validate the artifact set as a coherent delivery plan:

- **Plan-to-requirement fidelity**: every plan task traces to a requirement.
  No task may contradict a requirement. If a requirement says "reuse X," the
  plan must not prescribe "copy X." Contradictions are blockers (`needs_work`).
- **Coverage completeness**: every requirement has at least one plan task.
  Orphan requirements with no plan tasks are blockers.
- **Verification chain**: the plan's verification steps, taken together, would
  satisfy the DoD gates. No gap between "plan done" and "DoD met."

### 2. DOR gate validation

Validate all eight DOR gates:

1. Intent & success — problem and outcome explicit.
2. Scope & size — atomic, fits one session.
3. Verification — tests or observable checks defined.
4. Approach known — technical path clear in the plan.
5. Research complete — third-party dependencies researched.
6. Dependencies & preconditions — listed and blocked in roadmap if needed.
7. Integration safety — can merge incrementally.
8. Tooling impact — scaffolding procedures updated if applicable.

### 3. Review-readiness preview

Check whether the plan would survive each review lane without findings:

- Does the plan account for test expectations?
- Does the plan address security review concerns?
- Does the plan include documentation and config surface updates where needed?
- Are the rationale annotations sufficient for the builder to avoid shortcuts?

Gaps in review-readiness are `needs_work` — not blockers, but the plan needs
enrichment before the builder can execute safely.

### 4. Assign gate result

Write to `todos/{slug}/state.yaml`:

```yaml
dor:
  last_assessed_at: "<now ISO8601>"
  score: <1..10>
  status: "<pass|needs_work|needs_decision>"
  schema_version: 1
  blockers: []
  actions_taken:
    requirements_updated: false
    implementation_plan_updated: false
```

Threshold constants:

- Target quality: score >= 8 for pass.
- Decision required: score < 7 triggers `needs_decision`.

### 5. Write gate report

Update `todos/{slug}/dor-report.md` with:

- Gate verdict and score.
- Cross-artifact validation results.
- DOR gate results (per gate: pass/fail with evidence).
- Review-readiness assessment.
- Exact unresolved blockers if any.

### 6. Commit and go idle

Commit all todo artifact changes. The commit is the delivery mechanism — your
caller verifies the commit exists, not the file state on disk.

Go idle. Your caller will read the committed verdict and may open a direct
conversation if quality needs iteration.

## Outputs

1. Finalized `state.yaml` gate verdict.
2. Updated `dor-report.md` with comprehensive gate assessment.
3. All gate artifacts committed to git.

## Recovery

1. If evidence is insufficient, set `needs_decision` and list required decisions.
2. If contradictions exist between artifacts, mark `needs_work` and describe exact fixes.
3. Tighten artifacts with minimal edits when factual gaps are small. Do not author
   large new scope in gate mode.
