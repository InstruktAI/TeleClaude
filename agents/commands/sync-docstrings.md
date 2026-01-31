---
description: Update inline docstrings/JSDoc/comments to match current code behavior.
argument-hint: '[scope]'
---

@~/.teleclaude/docs/software-development/role/builder.md
@~/.teleclaude/docs/software-development/procedure/lifecycle/documentation/sync-docstrings.md

# Synchronize Docstrings

You are now the Builder.

## Purpose

Align inline documentation with actual code behavior.

## Inputs

- Scope: "$ARGUMENTS" (optional path/feature/component)
- Repository codebase

## Outputs

- Updated docstrings/comments in code
- Summary of files changed

## Steps

- If a scope is provided, focus on that area; otherwise cover the whole repo.
- Update docstrings/JSDoc/comments to match current behavior.
- Do not modify `docs/`.
- Report changed files only (no content diff).
