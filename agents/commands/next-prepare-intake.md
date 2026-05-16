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
- @docs/_snippets/slug-resolution.md

## Purpose

Interview the Product Owner role, produce the `prd` artifact, and record any
phase skip stamps justified by the work's size.

## Inputs

- Slug: "$ARGUMENTS"
- Session `ADDITIONAL CONTEXT`; `human_in_loop: false` means dispatch `/next-emulate-po`
  [OPTIONAL: only when slug was provided]:
- `telec todo artifacts read {slug} input`
- Existing `prd` artifact when present
<!-- DEPRECATED: `requirements-review-findings` artifact may exist on older todos from a prior workflow that had a dedicated requirements-review step. Read if present. Remove this bullet and the matching `ARTIFACT_REQUIREMENTS_REVIEW_FINDINGS` constant in `teleclaude/constants.py` once no in-flight todos carry the artifact. -->
- Deprecated `requirements-review-findings` artifact if present (see DEPRECATED note in source)

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
