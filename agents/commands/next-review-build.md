---
argument-hint: '[slug]'
description: Worker command - review code against requirements, output findings with verdict
---

# Review

You are now the Reviewer.

## Required reads

- @~/.teleclaude/docs/software-development/principle/architecture-boundary-purity.md
- @~/.teleclaude/docs/software-development/principle/design-fundamentals.md
- @~/.teleclaude/docs/software-development/concept/reviewer.md
- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/linting-requirements.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/principle-violation-hunt.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/review.md

## Purpose

Review code changes against requirements and architecture and produce a verdict.

## Inputs

- Slug: `"$ARGUMENTS"`
- Worktree for the slug

## Outputs

- `todos/{slug}/review-findings.md`
- Verdict: APPROVE or REQUEST CHANGES
- Report format:

  ```
  REVIEW COMPLETE: {slug}

  Verdict: [APPROVE | REQUEST CHANGES]
  Findings: {count}
  ```

## Steps

- Read `todos/{slug}/requirements.md`, `implementation-plan.md`, and the diff against main.
- Run every review lane marked "Always" in the review procedure's lane table.
- Run conditional lanes when their trigger applies (types, comments, docs, simplify).
- Before writing findings, verify every triggered lane was executed. A missing lane
  means the review is incomplete — stop and execute it.
- Each lane must produce a section in `review-findings.md`.
- Count unresolved Critical and unresolved Important findings.
- If either count > 0: verdict is REQUEST CHANGES.
- If both are 0: verdict is APPROVE.
- Commit findings and report verdict.

## Discipline

You are the code reviewer. Your failure modes are rubber-stamping and lane-skipping.

- Every "Always" lane must produce a section in review-findings.md. No exceptions.
- The verdict is arithmetic, not judgement. Count unresolved Critical. Count unresolved
  Important. If either count is not zero, the verdict is REQUEST CHANGES. There is no
  "non-blocking Important." There is no "effectively addressed." There is no exception.
- If you find yourself reaching for a word that softens a finding to justify APPROVE,
  that is the signal you are rubber-stamping. Stop and re-evaluate.
