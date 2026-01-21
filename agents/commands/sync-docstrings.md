---
description: Update inline docstrings/JSDoc/comments to match current code behavior.
argument-hint: "[scope]"
---

# Synchronize Docstrings

Align inline documentation with actual code behavior. This command is atomic and idempotent.

## Scope

ARGUMENT: "$ARGUMENTS"

- ARGUMENT: optional focus area (path, feature, or component). If omitted, cover the whole repo.
- Always operate from project root to keep paths correct.

## Mandatory Procedure

@~/.agents/docs/global-snippets/software-development/procedure/lifecycle/documentation/sync-docstrings.md

## Output

- Updated docstrings in code.
- No changes to docs/ or snippets.
