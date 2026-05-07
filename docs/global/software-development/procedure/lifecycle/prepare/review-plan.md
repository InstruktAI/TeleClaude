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

- `telec todo artifacts read {slug} implementation-plan` exists.
- `telec todo artifacts read {slug} requirements` exists and is approved.

## Steps

### 1. Read context

- `telec todo artifacts read {slug} implementation-plan` — the artifact under review.
- `telec todo artifacts read {slug} requirements` — the approved requirements it must satisfy.
- `telec todo artifacts read {slug} input` — original human thinking.
- Relevant codebase files referenced in the plan.
- The code review procedure — to understand what the reviewer will check.
- Apply the domain-context loading rule from the preparation artifact quality
  policy: identify which specs the plan touches and load them before
  validation begins.

### 2. Substantive delivery analysis

Structural coverage ("a task exists for this requirement") is not sufficient.
Produce a `Delivery analysis` section in `plan-review-findings.md` with one
entry per requirement success criterion.

For each success criterion in `requirements.md`:

1. Quote the criterion verbatim.
2. Quote the task body text (or multiple tasks' bodies) that delivers it.
3. State, in one sentence, how the quoted task text delivers the quoted
   criterion — naming the specific file edits, config changes, test additions,
   or other concrete deliverables the task prescribes.

Findings:

- Criterion not addressed by any task body -> **Requirement-Violation** (the
  highest severity; see `work/review` for the severity schema). A task bearing
  the requirement's name whose body narrows the criterion is a
  Requirement-Violation regardless of whether the task exists.
- Task body quotes criteria it does not deliver -> Critical.
- Orphan task (no requirement) -> Important (gold-plating risk).
- Task contradicts requirement -> Critical.

The reviewer cannot approve the plan while any criterion lacks a Delivery
analysis entry that names concrete deliverables.

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

- Every task has a rationale explaining _why_ this approach. Task with no
  rationale -> Important. Rationale that contradicts codebase patterns or
  loaded domain specs -> Critical.
- Every task has a verification step. Task with no verification -> Important.
  Verification that doesn't prove the task is done -> Important.
- Referenced file paths are explicit in the plan tasks for grounding review.
  Missing or incomplete -> Important.

### 5. Grounding

Apply the grounding rule from the preparation artifact quality policy. Verify
plan tasks against the domain specs loaded in step 1. Plans that reference
non-existent APIs, wrong schema fields, or incorrect directory structures are
defective — the builder will discover the error at build time, wasting a
session.

### 6. Review lane anticipation

Apply the DoD-driven review-awareness rule from the preparation artifact
quality policy. Produce a `Lane anticipation` section in
`plan-review-findings.md` with one entry per requirement, per triggered lane.

Each entry names the specific artifact the build-review lane will validate
and the plan task that produces it:

- **Tests**: name the test file and the specific assertions each task delivers.
  "Tests" as a category is not compliance.
- **Security**: name the validation point, the auth check, and the task that
  adds them.
- **Documentation**: name the doc file, the section updated, and the task
  that updates it.
- **Config surface**: name the config key, the wizard entry, the sample line,
  and the spec section — each with the task that delivers it.
- **Browser-based frontend or web UI**: name the Playwright smoke path and
  the task that records evidence for build and review.

A lane triggered by any requirement but not addressed by a named deliverable
per that requirement is an Important finding. Auto-remediate by inserting the
missing task when the gap is localized; otherwise mark `needs_work`.

### 7. Policy compliance

Check the plan against:

- **Code quality policy**: does the plan prescribe patterns consistent with
  existing codebase conventions?
- **Testing policy**: are test expectations aligned with testing standards?
- **Fallback policy**: does the plan introduce unjustified fallback paths?
  Every fallback must be justified by UX necessity.
- **Intelligence boundaries** (per `principle/intelligence-boundaries`):
  reject plan tasks that prescribe regex / classifier / scorer / auto-fixer
  code on free-text content. Patterns: hardcoded vocabulary tables;
  word-count thresholds for "is this meaningful?"; `is_*` / `should_*`
  predicates on natural language; auto-rewriters that edit agent artifacts
  to match structural rubrics. The defining test: would the task be
  unnecessary if the agent's briefing said the right thing? If yes, the
  task belongs in the briefing, not the plan. Critical — these accumulate
  silently and corrupt the codebase faster than coupling violations
  because every implementation looks "well-typed and narrow."

Policy violations are Critical findings.

### 8. Auto-remediate localized findings

Default behavior is to act in place. If a finding is localized, high-confidence,
and does not change intent, the reviewer should fix the plan directly in this
same pass instead of handing it back.

Localized means all of the following are true:

- No requirement intent changes.
- No new architectural decision is introduced.
- Scope stays within the reviewed planning artifacts and related grounding metadata.
- The reviewer can fully validate the fix from current context.

Not allowed — route via `needs_work` instead:

- Adding new tasks not traceable to requirements.
- Changing scope or splitting the todo.
- Inventing architectural decisions not grounded in requirements or codebase.

### 9. Write verdict

Stamp the review verdict:

```bash
telec todo stamp {slug} --verdict approve --phase plan_review
# or
telec todo stamp {slug} --verdict needs_work --phase plan_review
```

Verdict rules:

- `approve` only when unresolved Critical and unresolved Important findings are both zero.
- `needs_work` when any unresolved Critical or Important finding remains.

If unresolved findings exist, write them via `telec todo artifacts write {slug} plan-review-findings <content>`
with severity levels (Critical, Important) following the same format as code review
findings, including the policy citation requirement defined in `lifecycle/work/review` §6.

If no unresolved findings remain, do not write a new findings artifact.

### 10. Commit and report

Commit all files in the worktree. Report:

```
PLAN REVIEW: {slug}

Verdict: [APPROVE | NEEDS WORK]
Findings artifact: plan-review-findings when NEEDS WORK
```

## Outputs

- Verdict stamped with `telec todo stamp`.
- `telec todo artifacts read {slug} plan-review-findings` if findings exist.
- Commit containing review artifacts.

## Recovery

- If unresolved Critical or Important findings remain after auto-remediation,
  mark `needs_work`. The state machine will dispatch the plan drafter again
  with the findings.
- If requirements themselves are the problem (plan is correct but requirements
  are wrong), flag as blocker — requirements must be re-reviewed first.
