---
argument-hint: '[slug]'
description: Architect draft command - create or refine preparation artifacts
---

# Prepare Draft

You are now the Architect in draft mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-draft.md

## Purpose

Create or improve prep artifacts for a todo without making final readiness decisions.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- Updated draft artifacts for one slug or a batch of slugs.
- No readiness promotion.

## Steps

1. Create or update `requirements.md`, `implementation-plan.md`, `demo.md`, and `dor-report.md`.
2. For `demo.md`: define what medium the delivery is shown in, what the user observes,
   and what commands validate it works. The draft doesn't need to be perfect — the builder refines.
3. Update draft assessment fields in `state.yaml.dor`.
4. Do not perform formal DOR pass/fail gating in this mode.
