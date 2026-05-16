---
argument-hint: '[slug]'
description: Worker command - derive and write the code-grounded architecture artifact
---

# Prepare Architecture

You are now the Architect for prepare architecture.

## Required reads

- @~/.teleclaude/docs/general/principle/stewardship.md
- @~/.teleclaude/docs/general/principle/calibration.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/principle/design-fundamentals.md
- @~/.teleclaude/docs/software-development/principle/intelligence-boundaries.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/architecture.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md
- @docs/_snippets/slug-resolution.md

## Purpose

Ground the approved PRD in the codebase and produce an `architecture` artifact
that downstream test-specs and implementation planning can rely on.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} prd`
- Existing `architecture-review-findings` when present
- Relevant code paths discovered from the PRD and codebase

## Outputs

- `architecture` via `telec todo artifacts write {slug} architecture <content>`

## Steps

Follow the architecture procedure.

## Discipline

Follow the architecture procedure's discipline.
