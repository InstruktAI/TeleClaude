---
id: teleclaude/architecture/context-index
type: architecture
scope: project
description: Snippet index generation that produces docs/index.yaml from snippet frontmatter.
requires: []
---

Purpose
- Provide a deterministic index of available snippets for context selection.

Inputs/Outputs
- Inputs: docs/snippets markdown files with frontmatter.
- Outputs: docs/index.yaml containing snippet metadata and resolved dependencies.

Invariants
- Snippet IDs must be unique.
- requires entries are resolved relative to the snippet file path.
