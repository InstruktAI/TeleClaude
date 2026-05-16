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
- @~/.teleclaude/docs/_snippets/slug-resolution.md

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

- Follow the architecture procedure.
- Load the code and project architecture docs needed to verify every affected surface you name.
- Write the architecture artifact with explicit N/A sections where a standard section does not apply.
- Do not stamp `architecture_approved`; that stamp is reserved for human approval after review.
- Go idle after writing the artifact.

## Discipline

You are translating product intent into technical shape. Do not implement,
do not write tests, and do not invent one-off platform patterns when a standard
scaffold or flavor should exist.
