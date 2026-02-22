---
argument-hint: '[slug]'
description: Architect gate command - formal DOR validation and readiness decision
---

# Prepare Gate

You are now the Architect in gate mode.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-gate.md

## Purpose

Run formal DOR validation for preparation artifacts produced by a separate draft worker.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- Final DOR gate result for one slug or a batch of slugs.
- Eligibility for readiness transition where criteria are met.

## Steps

1. Validate and tighten existing draft artifacts with minimal changes.
2. Set canonical DOR gate outcome in `state.yaml`.
3. Do not author large new scope in this mode.
4. Gate mode is the only mode allowed to trigger readiness transition criteria.
