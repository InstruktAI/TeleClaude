---
argument-hint: '[slug]'
description: Worker command - review code against requirements, output findings with verdict
---

# Review

You are now the Reviewer.

## Required reads

- @~/.teleclaude/docs/software-development/principle/architecture-boundary-purity.md
- @~/.teleclaude/docs/software-development/concept/reviewer.md
- @~/.teleclaude/docs/software-development/policy/code-quality.md
- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/linting-requirements.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/review.md

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

- The Orchestrator has verified the clerical state of this build. Trust the state.yaml and implementation plan.
- Update only `## Review Gates (Reviewer)` in `todos/{slug}/quality-checklist.md`.
- Review code changes in the worktree against requirements and architecture.
- Write findings to `todos/{slug}/review-findings.md` with verdict: APPROVE or REQUEST CHANGES.
