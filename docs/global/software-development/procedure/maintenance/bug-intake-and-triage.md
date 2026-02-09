---
id: 'software-development/procedure/maintenance/bug-intake-and-triage'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Fast bug intake and triage method for small teams: classify impact quickly and force clear outcomes.'
---

# Bug Intake And Triage — Procedure

## Goal

Turn incoming bugs into quick, consistent decisions with clear ownership.

## Preconditions

- An issue intake channel exists (for example GitHub issues).
- Severity levels are agreed by the team.
- Triage owner for the current cycle is assigned.

## Steps

1. Capture minimum intake fields:
   - symptom,
   - user impact,
   - reproduction clues,
   - expected vs actual behavior.
2. Assign severity quickly:
   - P0: service unusable,
   - P1: major core-flow flakiness,
   - P2: annoying but usable,
   - P3: low-impact polish.
3. Force one decision per issue:
   - do now,
   - schedule,
   - close.
4. Assign owner and next action.
5. Re-triage if impact/frequency changes.

Five-minute triage rule:

- If P0/P1: assign immediately.
- If not P0/P1: decide based on recurring user pain and practical cost.
- No issue leaves triage without outcome.

## Outputs

- Every new bug has:
  - severity,
  - outcome,
  - owner,
  - next action.
- P0/P1 bugs have explicit target timing.

## Recovery

If triage backlog grows or issues stay undefined:

1. Batch-triage oldest issues first.
2. Close duplicates aggressively.
3. Move ambiguous issues to a reproduction owner.
4. Enforce “no undefined state” rule before accepting new backlog growth.
