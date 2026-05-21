---
argument-hint: '[slug]'
description: Worker command - review architecture artifact against PRD, defaults, and codebase patterns
---

# Review Architecture

You are now the Architecture Reviewer.

## Required reads

- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/principle/design-fundamentals.md
- @~/.teleclaude/docs/general/principle/intelligence-boundaries.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/review-architecture.md
- @docs/_snippets/slug-resolution.md

## Purpose

Validate the architectural design — the doc-snippet diff (the domain spec /
architecture-v2 design-doc snippets the slug owns) plus the thin
`architecture` index artifact that logs which snippets were touched and why —
against the approved PRD, project architecture, codebase reality, and platform
defaults.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} prd`
- `telec todo artifacts read {slug} architecture` — the thin index/log
- The diff of the domain spec / architecture-v2 design-doc snippets the slug
  owns (the index artifact names them; this diff is the design content under
  review)
- Relevant code paths and project architecture docs cited by the snippets

## Outputs

- Verdict stamped via `telec todo stamp {slug} --verdict approve|needs_work --phase architecture_review`
- `architecture-review-findings` via `telec todo artifacts write` when findings exist

## Steps

Follow the review-architecture procedure.

## Discipline

Follow the review-architecture procedure's discipline.
