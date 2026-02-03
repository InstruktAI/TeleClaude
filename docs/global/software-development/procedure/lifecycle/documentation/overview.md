---
description: Documentation phase ensuring inline docstrings and docs match the code.
id: software-development/procedure/lifecycle/documentation/overview
scope: domain
type: procedure
---

# Overview — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/documentation/sync-docstrings.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/documentation/sync-docs.md

## Goal

Documentation is a distinct lifecycle phase. It ensures the codebase and its inline documentation are aligned before finalization.

Run the phase in order:

1. **Sync Docstrings** — align inline docstrings/comments with actual code behavior.
2. **Sync Docs** — regenerate `docs/` from code + docs.

This phase is atomic and idempotent.

## Preconditions

- Code changes are complete and tested.

## Steps

1. Run docstring synchronization.
2. Run docs synchronization and validation.
3. Review outputs for completeness.

## Outputs

- Docstrings and docs aligned with code changes.

## Recovery

- If sync fails, fix docstrings/docs and rerun the phase.
