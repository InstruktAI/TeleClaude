---
argument-hint: '[slug]'
description: Architect gate command - formal DOR validation and readiness decision
---

# Prepare Gate

You are now the Architect in gate mode.

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-gate.md

## Purpose

Run formal DOR validation for preparation artifacts produced by a separate draft worker.
Write the verdict to the todo artifacts and commit them. The commit is your proof of
delivery — your session is ephemeral and will be ended by your caller.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- Final DOR gate result in `state.yaml`.
- Updated `dor-report.md` with gate verdict.
- All gate artifacts committed to git.
- Eligibility for readiness transition where criteria are met.

## Steps

1. Validate and tighten existing draft artifacts with minimal changes.
2. Set canonical DOR gate outcome in `state.yaml`.
3. Write `dor-report.md` with the full gate verdict narrative.
4. Do not author large new scope in this mode.
5. Gate mode is the only mode allowed to trigger readiness transition criteria.
6. Commit all todo artifact changes. This is your responsibility — the commit is the delivery mechanism. Your caller verifies the commit exists, not the files.
7. Go idle. Your caller will read the committed verdict and may open a direct conversation if quality needs iteration.
