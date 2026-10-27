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

- **Keeps memories current, and collects business items as prospects.** A
  memory about a person is current or retired, kept current by memory agents
  rather than accumulated (`local/projects/teleclaude/spec/feature/memory/memory-curation`).
  Business items from help-desk conversations — what visitors ask for, complain
  about, or are confused by — are collected as prospects for the home that owns
  the desk; they are raw material, never used as memories.

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

### Governing designs and decisions

- `local/projects/teleclaude/design/architecture/memory-system` — storing, searching and injecting observations
- `local/projects/teleclaude/adr/0002-memory-uses-triples` — observations as triples
- `local/projects/teleclaude/adr/0003-memory-event-store-semantics` — append-only memory writes
- `local/projects/teleclaude/adr/0004-two-memory-categories` — the two observation categories
- `local/projects/teleclaude/adr/0005-scraper-only-memory-writer` — extraction agents as the only memory writers
- `local/projects/teleclaude/adr/0006-mandatory-dedup-against-doc-snippets` — dedup against documentation before saving
- `local/projects/teleclaude/adr/0007-provenance-via-mirror-id` — the mirror id as an observation's provenance
- `local/projects/teleclaude/adr/0008-idle-close-cadence-whole-session` — when extraction runs over a session
- `local/projects/teleclaude/adr/0009-skill-pattern-detection-deferred` — deferral of skill-pattern detection

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
