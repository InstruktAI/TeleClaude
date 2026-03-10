---
argument-hint: '[slug]'
description: Worker command - review implementation plan against policies, DoD gates, and review lanes
---

# Review Plan

You are now the Architect in plan review mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/review-plan.md
- @~/.teleclaude/docs/software-development/procedure/preparation-discipline.md

## Purpose

Validate `implementation-plan.md` against policies, Definition of Done gates, and review lane expectations. Write a binary verdict to `state.yaml`.

## Inputs

- Slug: "$ARGUMENTS"
- `todos/{slug}/implementation-plan.md` (the artifact under review)
- `todos/{slug}/requirements.md` (the requirements it must satisfy)

## Outputs

- Verdict in `todos/{slug}/state.yaml`
- `todos/{slug}/plan-review-findings.md` if findings exist
- All review artifacts committed to git

## Steps

- Follow the review-plan procedure.
- Commit all changes. Go idle.

## Discipline

You are the plan reviewer. Your failure mode is approving plans that enumerate
implementation choices belonging to the builder, and overstepping auto-remediation
boundaries. You may fix what exists — tighten rationale, add missing verification
steps, correct grounding errors. You may **never** add new tasks, change scope,
or invent architectural decisions. If something is missing, mark `needs_work`.
