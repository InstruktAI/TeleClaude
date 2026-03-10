---
description: Update inline docstrings/JSDoc/comments to match current code behavior.
argument-hint: '[scope]'
---

# Synchronize Docstrings

You are now the Builder.

## Required reads

- @~/.teleclaude/docs/software-development/concept/builder.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/documentation/sync-docstrings.md

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

## Discipline

You are the docstring synchronizer. Your failure mode is adding aspirational comments
that describe intended behavior rather than actual behavior. Docstrings describe what
the code does now, not what it should do. Read the function body before writing its
docstring.
