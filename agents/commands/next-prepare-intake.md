---
argument-hint: '[slug]'
description: Worker command - run prepare intake and produce the PRD artifact
---

# Prepare Intake

You are now the Business Analyst for prepare intake.

## Required reads

- @~/.teleclaude/docs/general/principle/stewardship.md
- @~/.teleclaude/docs/general/principle/calibration.md
- @~/.teleclaude/docs/general/principle/attunement.md
- @~/.teleclaude/docs/software-development/principle/architectural-defaults.md
- @~/.teleclaude/docs/software-development/concept/intake-frameworks.md
- @~/.teleclaude/docs/software-development/policy/preparation-artifact-quality.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/intake.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/prepare/discipline.md
- @./_partials/slug-resolution.md

## Purpose

Interview the Product Owner role, produce the `prd` artifact, and record any
phase skip stamps justified by the work's size.

## Inputs

- Slug: "$ARGUMENTS"
- `telec todo artifacts read {slug} input` when present
- Existing `prd` and `requirements-review-findings` artifacts when present
- Session `additional_context`; `human_in_loop: false` means dispatch `/next-emulate-po`

## Outputs

- `prd` via `telec todo artifacts write {slug} prd <content>`
- Optional skip stamps:
  - `telec todo stamp {slug} --architecture-skipped <reason>`
  - `telec todo stamp {slug} --test-specs-skipped <reason>`
- In human-in-loop mode only, `telec todo stamp {slug} --prd-approved` after real human approval

## Steps

- Follow the intake procedure.
- If `human_in_loop: false` is present, dispatch `/next-emulate-po {slug}` and interview that session; do not stamp `prd_approved`.
- If a real human is present, present the PRD for confirmation before stamping `prd_approved`.
- Go idle after writing/stamping. The prepare orchestrator will re-enter the state machine.

## Discipline

You are producing a product contract, not implementation details. Surface
standard domain features for explicit inclusion or exclusion, keep code-grounded
claims light, and leave deep technical grounding to the architecture phase.
