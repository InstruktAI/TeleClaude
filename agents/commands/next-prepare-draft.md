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

1. Create or update `requirements.md`, `implementation-plan.md`, and `dor-report.md`.
2. Update draft assessment fields in `state.json.dor`.
3. Do not set item phase to `ready` in `state.json` in this mode.
4. Do not perform formal DOR pass/fail gating in this mode.
