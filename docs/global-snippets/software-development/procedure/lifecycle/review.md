---
description:
  Review phase. Verify requirements, code quality, tests, and deliver verdict
  with findings.
id: software-development/procedure/lifecycle/review
requires:
  - software-development/standards/code-quality
  - software-development/standards/testing
  - software-development/standards/linting-requirements
scope: domain
type: procedure
---

# Lifecycle: Review

## Requirements

@docs/global-snippets/software-development/standards/code-quality.md
@docs/global-snippets/software-development/standards/testing.md
@docs/global-snippets/software-development/standards/linting-requirements.md

## 1) Determine Slug

- If slug provided: use it.
- If not: read `todos/roadmap.md` and find first `[>]` without `review-findings.md`.

## 2) Load Context

Read:

1. `todos/{slug}/requirements.md`
2. `todos/{slug}/implementation-plan.md`
3. `README.md`, `AGENTS.md`, `docs/*` for project patterns

## 3) Identify Changes

Use merge-base to avoid comparing against unrelated main commits:

```bash
git diff $(git merge-base HEAD main)..HEAD --name-only
git diff $(git merge-base HEAD main)..HEAD
```

## 4) Pre-Review Completeness Checks

### Deferrals Scrutiny

If `deferrals.md` exists, verify each deferral is justified.
A deferral is justified only when the decision changes architecture/contracts or needs external input.
If unjustified, add a finding and set verdict to REQUEST CHANGES.

### Implementation Plan Complete

If any build task is unchecked, add a finding and set verdict to REQUEST CHANGES.

## 5) Review Lanes

Dispatch review aspects in parallel where possible:

| Aspect   | When to use              | Skill                      | Task                              |
| -------- | ------------------------ | -------------------------- | --------------------------------- |
| code     | Always                   | next-code-reviewer         | Find bugs and pattern violations  |
| tests    | Test files changed       | next-test-analyzer         | Evaluate coverage and quality     |
| errors   | Error handling changed   | next-silent-failure-hunter | Find silent failures              |
| types    | Types added/modified     | next-type-design-analyzer  | Validate type design              |
| comments | Comments/docs added      | next-comment-analyzer      | Check accuracy                    |
| simplify | After other reviews pass | next-code-simplifier       | Simplify without behavior changes |

## 6) Write Findings

Write to `todos/{slug}/review-findings.md` using structured severity sections and a binary verdict:

- Critical issues (must fix)
- Important issues (should fix)
- Suggestions (nice to have)
- Verdict: APPROVE or REQUEST CHANGES

## 7) Update State

Set `todos/{slug}/state.json` field `review` to `approved` or `changes_requested`.

## 8) Commit

Commit all review findings.

## 9) Report

Report summary and verdict to the caller.
