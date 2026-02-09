---
argument-hint: '[slug]'
description: Prepare router command - choose draft or gate explicitly
---

# Prepare

You are now the Prepare router.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/general/procedure/maintenance/next-prepare.md

## Purpose

This command is only a router. Choose exactly one mode and execute only that mode.

## Inputs

- Optional slug: "$ARGUMENTS"

## Outputs

- A single explicit dispatch choice:
  - `/next-prepare-draft [slug]`
  - `/next-prepare-gate [slug]`

## Steps

1. Inspect todo state.
2. If artifacts are missing or weak, run `/next-prepare-draft`.
3. If artifacts exist and need formal DOR validation, run `/next-prepare-gate`.
4. Never run draft and gate in the same worker turn.
