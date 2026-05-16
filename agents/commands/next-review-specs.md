---
argument-hint: '[slug]'
description: Worker command - review prose test specifications against PRD and architecture
---

# Review Test Specifications

You are now the Test Spec Reviewer.

## Required reads

- @~/.teleclaude/docs/software-development/policy/testing.md
- @~/.teleclaude/docs/software-development/policy/test-structure.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @docs/_snippets/slug-resolution.md

## Purpose

Review the prose `test-specs` artifact for behavioral coverage, rigor, and
alignment with the approved PRD and optional architecture.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} prd`
- `telec todo artifacts read {slug} architecture` when present
- `telec todo artifacts read {slug} test-specs`

## Outputs

- `spec-review-findings` via `telec todo artifacts write` when findings exist
- Verdict stamped via `telec todo stamp {slug} --verdict approve|needs_work --phase test_spec_review`

## Steps

Follow the review-specs procedure.

## Discipline

Follow the review-specs procedure's discipline.
