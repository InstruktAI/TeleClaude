---
description: Hold an adopted work item's builder for its current work driver's assessment, then continue repair in that same claiming group.
visibility: internal
delivered_by:
  - reviewed-pr-contributions
---

# Contribution Wait — Procedure

## Required reads

@docs/local/spec/feature/workflow/contribution-adoption.md
@~/.teleclaude/docs/general/policy/no-output-turn.md

## Goal

Hold the ordinary child builder for the adopted proposal while its work driver
assesses the subject, then continue the assigned repair on that proposal.

## Preconditions

- The ordinary work driver holds the prepared owning item and started this
  builder as its normal child in the same claiming group.
- The assignment identifies the item, adoption record and retained proposal.
- The session starts with upstream-owned instructions and configuration.

## Steps

1. Retain the assigned item, adoption and proposal identity. While current
   assessment is pending, settle into stillness under the no-output-turn
   policy; this waiting assignment performs no executable preparation.
2. Receive the current work driver's findings and continuation. Resume the
   assigned source repair or permitted validation in the retained worktree,
   answer its findings through the ordinary reply act, and continue with that
   driver through its review rounds.
3. A genuine kickback follows the ordinary item lifecycle's closing and
   source-retention contract. It supplies no transfer into another claiming
   group (`local/projects/teleclaude/design/architecture/lifecycle-state-machines`).

## Outputs

- The same waiting builder receives repair findings and continues on the
  retained proposal within its work driver's claiming group.

## Recovery

Report a changed proposal identity, unavailable source or preparation
contradiction with its evidence to the work driver
(`general/procedure/orchestration`).
