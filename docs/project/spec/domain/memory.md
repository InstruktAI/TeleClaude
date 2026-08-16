---
visibility: internal
description: Frozen v1 ownership anchor for durable preference observations and retrieval.
---

# Memory Domain Spec — Spec

## What it is

The v1 memory area owns durable observations about the human and projects,
along with search and context rendering over those observations. This anchor
describes the current appliance only.

## Canonical fields

- **Current behavior:** `docs/project/spec/feature/memory/` and memory-related
  feature specs that require this anchor.
- **Implementation roots:** `teleclaude/memory/`.
- **Maintenance stance:** see `project/spec/domain/glossary`. Replacement storage and authorization
  design belongs to TeleClaudeNext.

### Ownership boundary

- **Owns:** durable preference observations, their retrieval and search, and
  rendering those observations as context.
- **Does not own:** session transcripts, general project documentation, or
  decisions inferred from an observation by consuming domains.
- **Published contracts:** observation records, search queries, and rendered
  memory context.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
