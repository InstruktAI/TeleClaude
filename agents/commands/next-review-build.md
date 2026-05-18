---
argument-hint: '[slug]'
description: Worker command - review code against PRD and prepared artifacts, output findings with verdict
---

# Review

You are now the Reviewer.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/review.md
- @docs/_snippets/slug-resolution.md

## Purpose

Review code changes against the PRD, prepared artifacts, and architecture context, then produce a verdict.

## Inputs

- Slug: `"$ARGUMENTS"`
- Worktree for the slug

## Outputs

- Updated `review-findings` todo artifact persisted with `telec todo artifacts write {slug} review-findings "<content>"`
- Verdict: APPROVE or REQUEST CHANGES
- Report format:

  ```
  REVIEW COMPLETE: {slug}

  Verdict: [APPROVE | REQUEST CHANGES]
  Findings: {count}
  ```

## Steps

- Resolve the slug using `slug-resolution`.
- Follow `software-development/procedure/lifecycle/work/review` exactly for
  artifact loading, diff scope, review lanes, severity, findings persistence,
  verdict stamping, and reporting.
- Report using the format above.

## Discipline

This command is a thin activation wrapper. The review procedure is authoritative;
do not reinterpret or duplicate its artifact contract, lane rules, severity schema,
or verdict arithmetic here.
