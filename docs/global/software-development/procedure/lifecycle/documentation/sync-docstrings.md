---
description: Update inline docstrings and comments to match current code behavior.
id: software-development/procedure/lifecycle/documentation/sync-docstrings
scope: domain
type: procedure
---

# Sync Docstrings — Procedure

## Goal

Align inline documentation (docstrings/JSDoc/comments) with actual code behavior.

- **Stateless**: always run end-to-end, no conditional prechecks.
- **Code-truth only**: document what code does, not intentions.
- **Compact**: keep docstrings short and actionable.
- **No invention**: if behavior is unclear, ask or mark an Open Question.

- **Surface priority**: start with public APIs, adapters, and entrypoints.
- **Behavioral focus**: document inputs, outputs, side effects, errors, and invariants.
- **Boundary clarity**: emphasize what the code guarantees vs what callers must provide.
- **Avoid repetition**: don’t restate obvious code; capture intent and constraints.
- **Consistency**: align terminology with existing docs and type names.
- **Fast scan**: use `rg` to locate docstrings/comments, then capture a small code window to confirm behavior.

## Preconditions

- Code changes are complete and tests pass.

## Steps

1. Inventory docstrings/JSDoc/comments for public modules, classes, and functions.
2. Read the corresponding code and tests to confirm behavior.
3. Update docstrings to match inputs, outputs, invariants, side effects, and errors.
4. Remove aspirational or speculative language.
5. Flag unclear behavior with an **Open Questions** note if evidence is missing.

## Outputs

- Updated docstrings in code.

## Recovery

- If behavior is unclear, pause and request clarification before documenting.
