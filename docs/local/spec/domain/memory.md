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

- **local/projects/teleclaude/design/architecture/memory-system** — Persistent memory subsystem for storing, searching, and injecting relationship-centric observations into agent sessions.
- **local/projects/teleclaude/adr/0002-memory-uses-triples** — Memory observations are stored as (subject, predicate, object) triples rather than as flat title+narrative+type records.
- **local/projects/teleclaude/adr/0003-memory-event-store-semantics** — Memory writes are append-only — multiple rows with the same (subject, predicate, object) are allowed. Dedup is a read-time concern for downstream consumers, not a write-time check.
- **local/projects/teleclaude/adr/0004-two-memory-categories** — Memory observations are classified into exactly two categories — human (about a person) and project (about a project). A third "general" category was considered and deferred for lack of a concrete use case.
- **local/projects/teleclaude/adr/0005-scraper-only-memory-writer** — Memory is writable exclusively by the dedicated memory extraction agents (the scrapers). All other agents are prohibited from calling telec memories save.
- **local/projects/teleclaude/adr/0006-mandatory-dedup-against-doc-snippets** — Before saving any memory triple, the scraper must search existing doc snippets for substantive coverage and discard candidates that are already codified. Codified knowledge does not get re-encoded as memory.
- **local/projects/teleclaude/adr/0007-provenance-via-mirror-id** — Memory observations carry source_mirror_id as their provenance handle. Mirrors are eternal, so the pointer never rots; TeleClaude session_ids are ephemeral and native CLI session UUIDs are CLI-controlled.
- **local/projects/teleclaude/adr/0008-idle-close-cadence-whole-session** — Memory extraction runs over the whole session delta on two triggers — idle ≥30 minutes or session close. Per-turn windowing (e.g., Hermes-style every-N-turns) is not used for memory.
- **local/projects/teleclaude/adr/0009-skill-pattern-detection-deferred** — Skill pattern detection is deferred. Skills, when they come, will be per-human curation of external libraries (not memory-promotion). The future shape is captured in a design doc; no implementation in v2.

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
