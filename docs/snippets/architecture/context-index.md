---
id: architecture/context-index
description: Build docs/index.yaml from local snippets and resolve dependency paths.
type: architecture
scope: project
requires: []
---

# Context Index

## Purpose
- Generate an index of project snippets for context selection.

## Inputs/Outputs
- Inputs: `docs/snippets/**/*.md` frontmatter (id, description, requires).
- Outputs: `docs/index.yaml` with snippet IDs, descriptions, paths, and resolved requires.

## Invariants
- Files without frontmatter or missing id/description are skipped.
- Snippets with "baseline" in their path are ignored.
- `requires` paths are resolved relative to the snippet file and stored as project-relative paths.

## Primary Flows
- Scan snippets directory, parse frontmatter, build ordered index by snippet id.
- Write index payload to `docs/index.yaml`.

## Failure Modes
- Frontmatter parse errors are logged and skipped.
