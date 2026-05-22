---
description: 'Prepare phase overview. PRD intake, optional architecture (doc-snippet edits + thin index artifact), implementation planning, PRD-only human approval, and downstream reviewer gates.'
id: 'software-development/procedure/lifecycle/prepare'
scope: 'domain'
type: 'procedure'
visibility: 'public'
---

# Prepare — Procedure

## Goal

Produce reviewed, approved preparation artifacts for a todo without creating a
worktree or writing source code. Prepare v2 is a staged chain:

1. PRD intake.
2. Architecture, unless explicitly skipped.
3. Implementation plan.

The prepare state machine (`telec todo prepare`) owns sequencing. The
orchestrator calls it in a loop and dispatches the phase command it returns.

## Preconditions

- Target slug is active (not icebox, not delivered).
- If auto-spawned from `telec todo create`, the session may include
  `additional_context` with `human_in_loop: false`.

## Steps

### 1. Intake

The intake worker loads the intake procedure, interviews the Product Owner role
(the human by default; `/next-emulate-po` in standin mode), and writes the
`prd` artifact. A real human must approve the PRD before downstream prepare
phases proceed.

### 2. Architecture

For non-trivial work, the architecture worker grounds the approved PRD in the
codebase and authors the design directly into the affected domain spec /
architecture-v2 design-doc snippets, then writes a thin `architecture` index
artifact logging which snippets it touched and why. Small work may stamp
`architecture_skipped` with a reason.

### 3. Plan

The plan worker writes `implementation-plan` from the approved PRD and the
architecture (thin index plus the snippets it points to). If the work is not
atomic, the worker splits it instead of forcing an oversized plan.

### 4. Authority Gates

The state machine advances only from persisted evidence:

- `prd_approved` by the real human
- `architecture_review` verdict `approve` or `architecture_skipped`
- `plan_review` verdict `approve`

### 5. Drift

Grounding is derived, not stamped. When drift is detected, the drift reviewer
records `drift_reviewed` for the affected artifact. Cosmetic drift may proceed;
substantive drift blocks until the affected upstream artifact is reworked.

## Outputs

- `prd`
- `architecture` (thin index + doc-snippet edits) or `architecture_skipped`
- `implementation-plan`
- Human PRD approval, reviewer verdicts, skip stamps, and drift review stamps in todo state

## Recovery

- If any phase blocks, the state machine records the blocker and stops.
- Fix-forward only: preserve valid artifacts, clear downstream authority when
  an upstream artifact is refined, and re-enter with `telec todo prepare`.
