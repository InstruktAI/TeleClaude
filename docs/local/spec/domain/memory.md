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

- **Current behavior:** `docs/local/spec/feature/memory/` and memory-related
  feature specs that require this anchor.
- **Implementation roots:** `teleclaude/memory/`.
- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. Replacement storage and authorization
  design belongs to TeleClaudeNext.

### Ownership boundary

- **Owns:** durable preference observations, their retrieval and search, and
  rendering those observations as context.
- **Holds observations about people.** Memory records who a person is and how
  they work with the platform. It never records project knowledge — conventions,
  architecture, operational gotchas — nor decisions: those are documentation,
  shaped through the human-involved documentation process.

<!-- planned:help-desk-idle-memory-cycle -->

- **Holds business insights from help-desk conversations.** What visitors ask
  for, complain about, or are confused by is recorded for the home that owns the
  desk, beside the memories about each visitor
  (`local/projects/teleclaude/spec/feature/agent_runtime/desk-conversation-continuity`).

<!-- /planned:help-desk-idle-memory-cycle -->

- **Does not own:** session transcripts, general project documentation, or
  decisions inferred from an observation by consuming domains.
- **Published contracts:** observation records, search queries, and rendered
  memory context.
- **Also owns:** the subject each observation records — the person an
  observation about the human concerns, the project an observation about a
  project concerns, with that project's owner, or unknown when save cannot
  establish it — and the principal of the session it was extracted from. Every
  read that serves a caller admits observations through `identity`'s reach over
  those facts (`local/projects/teleclaude/spec/domain/identity`); memory decides no
  visibility of its own. Observations saved before subjects were recorded
  receive one once, from the project they name, or unknown.

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
