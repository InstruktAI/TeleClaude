---
id: 'software-development/procedure/lifecycle/prepare/review-plan'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Plan review phase. Validate implementation-plan.md against policies, DoD gates, and review lane expectations.'
---

# Review Plan — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/review.md

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
- Apply the domain-context loading rule from the preparation artifact quality
  policy: identify which specs the plan touches and load them before
  validation begins.

### 2. Requirement coverage

Every requirement in `requirements.md` must have at least one corresponding
task in the plan. Every task must trace back to a requirement. Findings:

- Orphan requirement (no plan task) -> Critical.
- Orphan task (no requirement) -> Important (gold-plating risk).
- Task contradicts requirement -> Critical.

### 3. Scope & size

Validate DOR Gate 2 (Scope & size). The plan must fit one builder session.
Apply the splitting heuristics from the Definition of Ready policy against
the plan's actual task list, not just the requirements prose.

- Plan spans multiple independently shippable workstreams -> Critical.
- Plan requires multiple phases that could be delivered separately without
  creating a half-working codebase -> Critical.

This is not auto-remediable — scope splits require the drafter, not the
reviewer. If scope fails, mark `needs_work`.

### 4. Plan-specific quality

Apply the plan-specific quality rules from the preparation artifact quality
policy:

- Every task has a rationale explaining *why* this approach. Task with no
  rationale -> Important. Rationale that contradicts codebase patterns or
  loaded domain specs -> Critical.
- Every task has a verification step. Task with no verification -> Important.
  Verification that doesn't prove the task is done -> Important.
- Referenced file paths are listed in `state.yaml.grounding.referenced_paths`.
  Missing or incomplete -> Important.

### 5. Grounding

Apply the grounding rule from the preparation artifact quality policy. Verify
plan tasks against the domain specs loaded in step 1. Plans that reference
non-existent APIs, wrong schema fields, or incorrect directory structures are
defective — the builder will discover the error at build time, wasting a
session.

### 6. Review lane anticipation

Apply the DoD-driven review-awareness rule from the preparation artifact
quality policy. Check whether the plan would survive each code review lane
without findings:

- **Tests**: does every plan task reference specific expected-failure tests it makes GREEN?
  Do referenced test names match actual test specs in the worktree?
- **Security**: does the plan address input validation, auth checks, and
  secret handling where applicable?
- **Documentation**: does the plan include help text, config surface, and
  README updates where the requirements imply user-facing changes?
- **Config surface**: if new config keys are introduced, does the plan include
  wizard, sample, and spec updates?
- **Demo**: does the plan include demo artifact updates?

Missing lane coverage is an Important finding.

### 7. Policy compliance

Check the plan against:

- **Code quality policy**: does the plan prescribe patterns consistent with
  existing codebase conventions?
- **Testing policy**: are test expectations aligned with testing standards?
- **Fallback policy**: does the plan introduce unjustified fallback paths?
  Every fallback must be justified by UX necessity.

Policy violations are Critical findings.

### 8. Auto-remediate localized findings

Default behavior is to act in place. If a finding is localized, high-confidence,
and does not change intent, the reviewer should fix the plan directly in this
same pass instead of handing it back.

Localized means all of the following are true:

- No requirement intent changes.
- No new architectural decision is introduced.
- Scope stays within the reviewed plan/demo artifacts and related grounding metadata.
- The reviewer can fully validate the fix from current context.

Not allowed — route via `needs_work` instead:

- Adding new tasks not traceable to requirements.
- Changing scope or splitting the todo.
- Inventing architectural decisions not grounded in requirements or codebase.

### 9. Write verdict

Update `todos/{slug}/state.yaml`:

```yaml
plan_review:
  verdict: "approve" | "needs_work"
  reviewed_at: "<now ISO8601>"
  findings_count: <n>
```

Verdict rules:

- `approve` only when unresolved Critical and unresolved Important findings are both zero.
- `needs_work` when any unresolved Critical or Important finding remains.
- Suggestion findings may remain unresolved under `approve`.

If unresolved findings exist, write them to `todos/{slug}/plan-review-findings.md`
with severity levels (Critical, Important, Suggestion) following the same format
as code review findings.

If no unresolved findings remain, remove stale `plan-review-findings.md` if present.

### 10. Commit and report

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

- If unresolved Critical or Important findings remain after auto-remediation,
  mark `needs_work`. The state machine will dispatch the plan drafter again
  with the findings.
- If requirements themselves are the problem (plan is correct but requirements
  are wrong), flag as blocker — requirements must be re-reviewed first.
