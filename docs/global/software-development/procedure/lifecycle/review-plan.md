---
id: 'software-development/procedure/lifecycle/review-plan'
type: 'procedure'
scope: 'domain'
description: 'Plan review phase. Validate implementation-plan.md against policies, DoD gates, and review lane expectations.'
---

# Review Plan — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/review.md

## Goal

Validate `implementation-plan.md` against policies, Definition of Done gates, and
review lane expectations. The plan must be good enough that a builder can execute
it without guessing and a reviewer finds no surprises.

## Preconditions

- `todos/{slug}/implementation-plan.md` exists.
- `todos/{slug}/requirements.md` exists and is approved.

## Steps

### 1. Read context

- `todos/{slug}/implementation-plan.md` — the artifact under review.
- `todos/{slug}/requirements.md` — the approved requirements it must satisfy.
- `todos/{slug}/input.md` — original human thinking.
- Relevant codebase files referenced in the plan.
- The code review procedure — to understand what the reviewer will check.

### 2. Requirement coverage

Every requirement in `requirements.md` must have at least one corresponding
task in the plan. Every task must trace back to a requirement. Findings:

- Orphan requirement (no plan task) → Critical.
- Orphan task (no requirement) → Important (gold-plating risk).
- Task contradicts requirement → Critical.

### 3. Rationale presence

Every task must explain *why* this approach was chosen. The rationale prevents
the builder from taking shortcuts. Findings:

- Task with no rationale → Important.
- Rationale that contradicts codebase patterns → Critical.

### 4. Verification completeness

Every task must have a verification step: a test to write, behavior to observe,
or check to run. The builder needs to know when each task is done. Findings:

- Task with no verification → Important.
- Verification that doesn't actually prove the task is done → Important.

### 5. Review lane anticipation

Check whether the plan would survive each code review lane without findings:

- **Tests**: does the plan include test tasks for every new behavior?
- **Security**: does the plan address input validation, auth checks, and
  secret handling where applicable?
- **Documentation**: does the plan include help text, config surface, and
  README updates where the requirements imply user-facing changes?
- **Config surface**: if new config keys are introduced, does the plan include
  wizard, sample, and spec updates?
- **Demo**: does the plan include demo artifact updates?

Missing lane coverage is an Important finding. The plan should pre-satisfy
what the reviewer will check.

### 6. Policy compliance

Check the plan against:

- **Code quality policy**: does the plan prescribe patterns consistent with
  existing codebase conventions?
- **Testing policy**: are test expectations aligned with testing standards?
- **Fallback policy**: does the plan introduce unjustified fallback paths?
  Every fallback must be justified by UX necessity.

Policy violations are Critical findings.

### 7. Referenced paths

Verify that `state.yaml.grounding.referenced_paths` lists all file paths
from the plan. These paths enable automated staleness detection. If missing
or incomplete, flag as Important.

### 8. Write verdict

Update `todos/{slug}/state.yaml`:

```yaml
plan_review:
  verdict: "approve" | "needs_work"
  reviewed_at: "<now ISO8601>"
  findings_count: <n>
```

If findings exist, write them to `todos/{slug}/plan-review-findings.md`
with severity levels (Critical, Important, Suggestion) following the same
format as code review findings.

### 9. Commit and report

Commit the verdict and any findings. Report:

```
PLAN REVIEW: {slug}

Verdict: [APPROVE | NEEDS WORK]
Findings: {count}
```

## Outputs

- Verdict in `todos/{slug}/state.yaml`.
- `todos/{slug}/plan-review-findings.md` if findings exist.
- Commit containing review artifacts.

## Recovery

- If the plan has Critical findings, mark `needs_work`. The state machine will
  dispatch the plan drafter again with the findings.
- If requirements themselves are the problem (plan is correct but requirements
  are wrong), flag as blocker — requirements must be re-reviewed first.
