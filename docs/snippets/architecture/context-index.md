---
id: teleclaude/architecture/context-index
type: architecture
scope: project
description: Snippet index generation that produces docs/snippets/index.yaml from snippet frontmatter.
requires: []
---

## Purpose

- Provide a deterministic index of available snippets for context selection.

## Inputs/Outputs

- Inputs: `docs/snippets/**/*.md` files with frontmatter.
- Outputs: `docs/snippets/index.yaml` containing snippet metadata and dependencies.

## Invariants

- Snippet IDs must be unique.
- requires entries are resolved relative to the snippet file path.

## Primary flows

- Scan snippet files, parse frontmatter, and collect metadata.
- Resolve `requires` against snippet IDs and paths.
- Write the consolidated index to `docs/snippets/index.yaml`.

## Failure modes

- Invalid or missing frontmatter entries are skipped with a warning.
