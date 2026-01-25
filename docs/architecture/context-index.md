---
id: teleclaude/architecture/context-index
type: architecture
scope: project
description: Snippet index generation that produces docs/index.yaml from snippet frontmatter.
---

# Context Index — Architecture

## Purpose

- Provide a deterministic index of available docs for context selection.

- Inputs: `docs/**/*.md` files with frontmatter.
- Outputs: `docs/index.yaml` containing snippet metadata and dependencies.

- Snippet IDs must be unique.
- requires entries are resolved relative to the snippet file path.

- Scan snippet files, parse frontmatter, and collect metadata.
- Resolve `requires` against snippet IDs and paths.
- Write the consolidated index to `docs/index.yaml`.

- Invalid or missing frontmatter entries are skipped with a warning.

- TBD.

- TBD.

- TBD.

- TBD.

## Inputs/Outputs

- TBD.

## Invariants

- TBD.

## Primary flows

- TBD.

## Failure modes

- TBD.
