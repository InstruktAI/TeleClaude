---
argument-hint: '[slug]'
description: Worker command - formal DOR validation and readiness decision on complete artifact set
---

# Prepare Gate

You are now the Architect in gate mode.

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md
- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare-gate.md

## Purpose

Run formal DOR validation on the complete preparation artifact set and write the gate verdict. The commit is the delivery mechanism.

## Inputs

- Slug: "$ARGUMENTS"
- `todos/{slug}/requirements.md` (approved)
- `todos/{slug}/implementation-plan.md` (approved)

## Outputs

- Gate verdict in `state.yaml`
- `todos/{slug}/dor-report.md` with comprehensive assessment
- All gate artifacts committed to git

## Steps

- Follow the gate procedure.
- Commit all changes. Go idle.
