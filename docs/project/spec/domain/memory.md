---
id: project/spec/domain/memory
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by: [v2-memory, v2-memory-cutover]
description: Memory bounded context — durable observations the platform accumulates about humans and projects. Triple-shaped, event-store-semantic, dedup-disciplined; the substrate of cross-session continuity. Scraper-only writes; pattern-matcher jobs read.
---

# Memory Domain Spec — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md

## What it is

The `memory` bounded context owns durable observations the platform accumulates over time about (a) specific humans and (b) specific projects. Observations are stored as **triples** — `(subject, predicate, object)` — tagged by category and provenance. Memory is authored exclusively by the **memory extraction agents** (the scrapers), invoked via `/extract-memory-human <session_id>` and `/extract-memory-project <session_id>`. No other agent writes to memory.

Memory is the substrate of cross-session continuity. A returning human is recognized by their accumulated triples. A project's evolving conventions, decisions, and frictions are recorded so downstream pattern-matchers can consume them and produce actual project artifacts (doc-snippet drafts, todos).

Memory is distinct from:

- **Context** (doc snippets, skills, agents) — codified, schema-validated, deployed reference content. Authored. Authoritative.
- **Session mirrors** — eternal full-text session transcripts. Per-session, unextracted.
- **Memory** — extracted, atomic, classified observations. Per-fact, scraper-authored, dynamic.

The dedup discipline (below) is what keeps memory from becoming a duplicate junk drawer next to the codified library.

## Canonical fields

### Ubiquitous language

**Observation (triple)**
: The atomic unit of memory. `(subject, predicate, object)`, tagged by `category` and `source_mirror_id`. Identified by its own UUID. The store is append-only: multiple rows with the same `(subject, predicate, object)` are allowed and meaningful (each represents a distinct observed occurrence).

**Category**
: `human` or `project`. Determines which predicate vocabulary applies and how the subject is interpreted. Categories are the classification axis of memory; they are NOT tiers in the memory-tiers concept (which describes the agent's memory gradient).

**Subject**
: For `human` category: the human's durable identifier — email when resolvable, identity-context string otherwise. For `project` category: the project slug. Opaque string; matched by exact equality.

**Predicate**
: A token from the per-category controlled vocabulary. Free-form predicates are rejected at save.

**Object**
: The value the predicate carries. Free-form text. Search-indexed.

**Source mirror id**
: The `mirror_id` of the session mirror this observation was extracted from. Provenance handle. Durable: mirrors are eternal, so this pointer never goes stale.

**Saved at**
: When the observation was persisted. Immutable.

### Storage shape

The store is **append-only event semantics**. Every save inserts a new row. Dedup happens at _processing_ time downstream, not at write time. The Tier-2 pattern-matcher reading the store aggregates by `(subject, predicate, object)` and uses `COUNT(*)` for salience. The scraper's only write-time obligation is the dedup-against-doc-snippets rule (below).

Row shape:

```
observation_id      UUID            generated at save
category            text            'human' | 'project'
subject             text            email | identity-context-string | project-slug
predicate           text            from per-category vocabulary
object              text            free-form, search-indexed
source_mirror_id    UUID            FK to session_mirrors
saved_at            timestamp       immutable
```

### Aggregates

#### Observation

- **Root:** `Observation` (the triple).
- **Contains:** the fields above.
- **Invariants:**
  - `category` ∈ {`human`, `project`}.
  - `predicate` is in the per-category controlled vocabulary; free-form predicates are rejected at save.
  - `subject` is non-empty; format depends on category.
  - `source_mirror_id` references an existing mirror row.
  - The store is append-only. Duplicates at `(subject, predicate, object)` are allowed; each represents a distinct observed occurrence with its own provenance.
- **Identifier:** `observation_id`.
- **Lifecycle:** Created via `telec memories save` (scraper-only). Never updated. Hard-deleted only via explicit operator cleanup. No automatic retention; rows persist until explicit delete. Project-category rows MAY be pruned by downstream pattern-matcher jobs once promoted to a project artifact (todo or doc-snippet draft); human-category rows persist indefinitely.

### Domain events emitted

#### `memory.observation.saved`

- **Emitted when:** a triple is persisted.
- **Payload:** `observation_id`, `category`, `subject`, `predicate`, `source_mirror_id`, `saved_at`.
- **Consumers:** project-category pattern-matcher jobs; audit log.
- **Idempotency key:** `observation_id`.

#### `memory.observation.deleted`

- **Emitted when:** a triple is removed.
- **Payload:** `observation_id`, `deleted_at`, `deleted_by_principal`.
- **Idempotency key:** `observation_id`.

### Use cases

#### UC-MEM-1: Scraper saves a triple

```
Given a memory extraction session has identified a candidate observation,
      classified its category and predicate, dedup'd against doc snippets
When the scraper runs:
     telec memories save --category <h|p> --subject <s> --predicate <p> --object <o> --source-mirror <id>
Then memory validates the predicate against the category's vocabulary
And persists the triple as a new row (append-only; no dedup at write time)
And emits memory.observation.saved
```

#### UC-MEM-2: Query triples for a subject

```
Given an agent wants "what does this human prefer?"
When they run:  telec memories search --category human --subject <email> --predicate prefers
Then memory returns all matching rows (multi-row results give weight by frequency)
```

#### UC-MEM-3: Session-start context injection

```
Given a session is starting for a human with a known email
When the context layer queries memory for that subject
Then memory returns the human's full corpus of triples (grouped or ranked by recency/frequency)
And the context layer renders them compactly for injection
```

#### UC-MEM-4: Pattern-matcher consumes project memories

```
Given the project memory pattern-matcher job runs on schedule
When it queries:  telec memories search --category project --subject <slug> --predicate requirement
Then memory returns all `requirement` rows for that project
And the pattern-matcher aggregates by (subject, predicate, object), uses COUNT(*) for salience
And promotes salient items to todos via `telec todo create`
```

### Dedup discipline (mandatory, write-time)

Before saving any triple, the scraper MUST:

1. **Search doc snippets** (`telec docs index` + `telec docs get`). If the candidate is substantively covered there — even with different wording — **discard**. Codified knowledge does not get re-encoded as memory.
2. **Save** the survivor.

The store does NOT dedup at write time across existing memory rows — repeated observations are meaningful (frequency signals salience). The dedup discipline is solely against the _codified_ library (doc snippets), to keep memory from duplicating authoritative knowledge.

This is the single most important rule in this spec. Without it, memory becomes a duplicate junk drawer next to the codified library and the system loses the ability to know what's authoritative.

### Scraper boundary (mandatory)

The memory extraction agents (the scrapers — one for human-category, one for project-category) are the **only** authorized writers to memory. They produce triples from a session mirror. They do **NOT**:

- Create todos.
- Create or modify doc snippets.
- Make cross-session pattern claims ("X happens repeatedly").
- Interpret human emotion or intent.
- Synthesize beyond what was demonstrated in the transcript.

Pattern recognition, artifact creation, and aggregation across sessions are downstream concerns owned by separate jobs that read accumulated memories. Direct `telec memories save` calls from any agent other than the scrapers are prohibited by policy.

### Cadence and trigger semantics

Extraction is triggered by one of two conditions on a session:

- **Idle threshold reached** — the session has been idle for ≥ 30 minutes since `last_activity`.
- **Session close** — the session has transitioned to closed/stopped.

Both triggers invoke the scrapers over the _whole session_ delta (no per-turn windowing). Each scraper reads the session's mirror (`session_mirrors.text_content`) and extracts the new content since its category's last-extraction marker for this mirror.

The trigger handler is the daemon's maintenance loop; no separate scheduler entry. Each scraper runs once per eligible session per trigger; concurrent dispatch for the same `(category, mirror_id)` is prevented by sidecar bookkeeping (operational concern, not a memory-domain detail).

### Context map position

- **Customer-Supplier downstream of `identity`** — human-category subject resolution depends on identity (email lookup, identity-context fallback).
- **Customer-Supplier downstream of `session_mirrors`** — observations carry `source_mirror_id`; the scrapers read mirror text content.
- **Open Host Service to pattern-matchers** — read access for downstream pattern-matcher jobs that produce project artifacts (todos, doc-snippet drafts).

## Allowed values

- `category`: `human`, `project`.
- `predicate` (human category) — see `docs/project/spec/feature/memory/extraction-human.md` for the controlled vocabulary.
- `predicate` (project category) — see `docs/project/spec/feature/memory/extraction-project.md` for the controlled vocabulary.

## Known caveats

- **Scraper-only writer.** Direct `telec memories save` calls from any agent other than the scrapers are policy violations and should be flagged.
- **Predicate vocabulary is closed per category.** Free-form predicates are rejected at save. Vocabulary changes require a feature-spec update.
- **Append-only.** No write-time dedup across existing memory rows. Frequency signals salience to downstream consumers.
- **No automatic retention for human-category rows.** They persist indefinitely. Pattern-matchers may flag stale or contradicted triples for human review.
- **Project-category rows MAY be pruned by downstream promoters** after being aggregated into project artifacts (todos, doc-snippet drafts). The promoter owns its own retention.
- **No interpretation.** The scrapers record demonstrated facts. Synthesis is downstream.
- **Doc-snippet dedup is mandatory.** Skipping it is the failure mode that turns memory into duplicate noise.
