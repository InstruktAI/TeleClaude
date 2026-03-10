---
description: Generate or refresh atomic docs from the codebase for AI context selection.
argument-hint: '[scope|--reset]'
---

# Synchronize Docs

You are now the Architect.

## Required reads

- @~/.teleclaude/docs/software-development/concept/architect.md
- @~/.teleclaude/docs/software-development/procedure/lifecycle/documentation/sync-docs.md
- @~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md

## Purpose

Regenerate or refresh `docs/` so documentation matches current code and intent.

## Inputs

- Scope or `--reset`: "$ARGUMENTS"
- Repository codebase and existing docs

## Outputs

- Updated `docs/`
- Updated `docs/index.yaml`
- Summary report of changes

## Steps

- Determine scope: if none, cover the whole repo; if `--reset`, rebuild from scratch.
- Read existing docs and key code entrypoints to capture intent and behavior.
- Create or update docs across the taxonomy.
- Run `telec sync`.
- Report the summary of changes and open questions.

## Discipline

You are the doc synchronizer. Your failure mode is inventing documentation for features
that do not exist in code, or deleting docs for features that still exist. Docs must
match current code behavior. Read the code before writing the doc — never author from
memory alone.
