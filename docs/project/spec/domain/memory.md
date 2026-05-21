---
id: project/spec/domain/memory
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by: [v2-memory, v2-memory-cutover]
description: Memory bounded context — durable observations the platform accumulates about humans and projects. Triple-shaped, tiered, dedup-disciplined; the substrate of cross-session continuity. Scraper-only writes; pattern-matcher jobs read.
---

# Memory Domain Spec — Spec

## What it is

The `memory` bounded context owns durable observations the platform accumulates over time about (a) specific humans and (b) specific projects. Observations are stored as **triples** — `(subject, predicate, object)` — tagged by tier and provenance. Memory is authored exclusively by the **session memory extraction agent** (the scraper), invoked via `/extract-memory <session_id>`. No other agent writes to memory.

Memory is the substrate of cross-session continuity. A returning human is recognized by their accumulated triples. A project's evolving conventions, decisions, and frictions are recorded so downstream pattern-matchers can consume them and produce actual project artifacts (doc-snippet drafts, todos).

Memory is distinct from:

- **Context** (doc snippets, skills, agents) — codified, schema-validated, deployed reference content. Authored. Authoritative.
- **Session mirrors** — eternal full-text session transcripts. Per-session, unextracted.
- **Memory** — extracted, atomic, tiered observations. Per-fact, scraper-authored, dynamic.

The dedup discipline (below) is what keeps memory from becoming a duplicate junk drawer next to the codified library.

## Tiers

Memory has **two tiers**. A third — "general" / population-wide — is deferred. It is added once a concrete use case appears that fits neither human nor project.

### Human tier — about this person

**Why it exists:**

- **Continuity.** Without per-human memory, every session starts cold. A returning help-desk customer should land on a system that already recognizes them and what they've said before.
- **Calibration without surveying.** Knowing the human's expertise, preferences, and constraints lets the agent set register correctly from the first message — no round-trip to ask "what's your background."
- **Salience weighting.** Recording which topics this human surfaces repeatedly tells downstream consumers what to attend to.

**Subject:** the human's durable identifier.

- **Primary form: email.** Resolvable for most internal humans (admins, members, contributors) via the person config.
- **Fallback form: identity-context string** (e.g., `whatsapp:31612345678`) when no email exists — anonymous help-desk customers entering via platform connectors.
- Both shapes are opaque strings; dedup works by exact equality.

**Predicate vocabulary** (closed, controlled):

| Predicate      | Multi-valued | Captures                                                |
| -------------- | ------------ | ------------------------------------------------------- |
| `role`         | no           | The human's role (admin, member, customer, contributor) |
| `expertise`    | yes          | Domains and depth they hold expertise in                |
| `working-on`   | yes          | What they're currently engaged with                     |
| `prefers`      | yes          | Positive preferences (style, format, approach)          |
| `dislikes`     | yes          | Negative preferences                                    |
| `goal`         | yes          | Articulated goals                                       |
| `constraint`   | yes          | Hard constraints they've stated                         |
| `decided`      | yes          | Choices they made (rationale baked into object)         |
| `mentioned`    | yes          | Topics surfaced — frequency in object or accumulated    |
| `relationship` | yes          | Other humans in their orbit                             |

Single-valued predicates replace on update; multi-valued accumulate distinct objects.

**Critical boundary:** human-tier triples are about the human *as a human*. The moment an observation is about the human *in relation to a specific project* (e.g., "Maurice's feedback on the TeleClaude memory subsystem"), it belongs in **project tier** with that project as subject. Human tier never references a project.

### Project tier — about this project

**Why it exists:**

- **Capture transient system insight.** Conventions, decisions, frictions, and requirements surface in conversations and would otherwise die at session-end. Memory is the upstream feed for project artifacts.
- **Cross-project routing.** A session in the help-desk project can produce an observation about TeleClaude itself. The scraper, primed with required reads for known projects, routes to the right project's memory regardless of which project the session is running in.
- **Decoupling sensing from acting.** The scraper just records. Pattern-matcher jobs read accumulated project memories and produce actual artifacts (doc-snippet drafts, todos). The scraper has no cross-session visibility and is not authorized to draft artifacts.

**Subject:** the project slug (e.g., `teleclaude`, `help-desk`).

**Predicate vocabulary** (closed, controlled):

| Predicate            | Multi-valued | Captures                                              |
| -------------------- | ------------ | ----------------------------------------------------- |
| `convention`         | yes          | A way-of-working that emerged or was affirmed         |
| `decided`            | yes          | A decision made (rationale baked into object)         |
| `friction`           | yes          | Something that broke, rubbed, or surprised painfully  |
| `requirement`        | yes          | An explicit ask — upstream of a future todo           |
| `gotcha`             | yes          | Counter-intuitive behavior, quiet trap                |
| `architectural-fact` | yes          | Design state of the system                            |
| `constraint`         | yes          | A limit the project enforces                          |
| `deferral`           | yes          | An explicit postponement (reason in object)           |
| `dependency`         | yes          | What this project relies on                           |
| `pattern`            | yes          | A recurring approach that works                       |
| `anti-pattern`       | yes          | A recurring approach that doesn't work                |
| `mentioned`          | yes          | Topic salience for this project                       |
| `open-question`      | yes          | Unresolved items, capture-and-revisit                 |

## Canonical fields

### Ubiquitous language

**Observation (triple)**
: The atomic unit of memory. `(subject, predicate, object)`, tagged by `tier` and `source_session_id`. Identified by its own UUID.

**Tier**
: `human` or `project`. Determines which predicate vocabulary applies and how the subject is interpreted.

**Subject**
: For `human` tier: email or identity-context string. For `project` tier: project slug. Opaque string; matched by exact equality for dedup.

**Predicate**
: A token from the per-tier controlled vocabulary. Free-form predicates are rejected at save.

**Object**
: The value the predicate carries. Free-form text. Search-indexed.

**Source session id**
: The session this observation was extracted from. Provenance for audit and re-extraction safety.

**Saved at**
: When the observation was persisted. Immutable.

### Aggregates

#### Observation

- **Root:** `Observation` (the triple).
- **Contains:** `observation_id` (UUID), `tier`, `subject`, `predicate`, `object`, `source_session_id`, `saved_at`.
- **Invariants:**
  - `tier` ∈ {`human`, `project`}.
  - `predicate` is in the per-tier controlled vocabulary; free-form predicates are rejected.
  - `subject` is non-empty; format depends on tier (email/identity-context for human; project slug for project).
  - `source_session_id` references an existing session record.
  - For single-valued predicates: `(subject, predicate)` is unique — saving a new object replaces the prior.
  - For multi-valued predicates: `(subject, predicate, object)` is unique — exact duplicates are skipped.
- **Identifier:** `observation_id`.
- **Lifecycle:** Created via `telec memories save` (scraper only). Mutated via the same save path with replace semantics for single-valued predicates. Hard-deleted via `telec memories delete`. No automatic retention; observations persist until explicit delete.

### Domain events emitted

#### `memory.observation.saved`

- **Emitted when:** a triple is persisted (created or single-valued replaced).
- **Payload:** `observation_id`, `tier`, `subject`, `predicate`, `source_session_id`, `saved_at`.
- **Consumers:** project-tier pattern-matcher jobs; audit log.
- **Idempotency key:** `observation_id`.

#### `memory.observation.deleted`

- **Emitted when:** a triple is removed.
- **Payload:** `observation_id`, `deleted_at`, `deleted_by_principal`.
- **Idempotency key:** `observation_id`.

### Use cases

#### UC-MEM-1: Scraper saves a triple

```
Given a /extract-memory session has identified a candidate observation,
      classified its tier and predicate, dedup'd against doc snippets and existing triples
When the scraper runs:
     telec memories save --tier <h|p> --subject <s> --predicate <p> --object <o> --source-session <id>
Then memory validates the predicate against the tier's vocabulary
And applies single-valued (replace) or multi-valued (skip-if-duplicate) semantics
And persists the triple
And emits memory.observation.saved
```

#### UC-MEM-2: Query triples for a subject

```
Given an agent wants "what does this human prefer?"
When they run:  telec memories search --tier human --subject <email> --predicate prefers
Then memory returns all triples matching subject + predicate (multi-valued accumulation)
```

#### UC-MEM-3: Session-start context injection

```
Given a session is starting for a human with a known email
When the context layer queries memory for that subject
Then memory returns all triples for the human's subject (full tier-h corpus for them)
And the context layer renders them compactly for injection
```

#### UC-MEM-4: Pattern-matcher consumes project memories

```
Given the project memory pattern-matcher job runs on schedule
When it queries:  telec memories search --tier project --subject <slug> --predicate requirement
Then memory returns all `requirement` triples for that project
And the pattern-matcher decides which to promote to todos via telec todo create
```

#### UC-MEM-5: Re-extraction safety via provenance

```
Given the scraper re-runs on a session whose transcript was previously partially processed
When it attempts to save a triple already extracted from this session
Then dedup catches the (subject, predicate, object) match
And the duplicate is skipped — no double-save
```

### Dedup discipline (mandatory)

Before saving any triple, the scraper MUST:

1. **Search doc snippets** (`telec docs index` + `telec docs get`). If the candidate is substantively covered there — even with different wording — **discard**. Codified knowledge does not get re-encoded as memory.
2. **Search existing triples** (`telec memories search`). If an equivalent triple is already saved, **discard** (multi-valued) or **update** (single-valued).
3. **Save** the survivor.

Without step 1, memory becomes a duplicate junk drawer next to the codified library and the system loses the ability to know what's authoritative. This is the single most important rule in this spec.

### Scraper boundary (mandatory)

The session memory extraction agent (the scraper) is the **only** authorized writer to memory. It produces triples from a session transcript. It does **NOT**:

- Create todos.
- Create or modify doc snippets.
- Make cross-session pattern claims ("X happens repeatedly").
- Interpret human emotion or intent.
- Synthesize beyond what was demonstrated in the transcript.

Pattern recognition, artifact creation, and aggregation across sessions are downstream concerns owned by separate jobs that read accumulated memories. Direct `telec memories save` calls from any agent other than the scraper are prohibited by policy.

### Context map position

- **Customer-Supplier downstream of `identity`** — subject resolution depends on identity (email lookup, identity-context fallback).
- **Customer-Supplier downstream of `agent_runtime`** — observations carry `source_session_id`; the scraper reads sessions via the session record.
- **Open Host Service to pattern-matchers** — read access for downstream pattern-matcher jobs.
- **No partnership with `session_mirrors`** — mirrors and memory operate independently. The scraper bridges them per session; the architectures stay separate.

## Allowed values

- `tier`: `human`, `project`.
- `predicate` (human tier): `role`, `expertise`, `working-on`, `prefers`, `dislikes`, `goal`, `constraint`, `decided`, `mentioned`, `relationship`.
- `predicate` (project tier): `convention`, `decided`, `friction`, `requirement`, `gotcha`, `architectural-fact`, `constraint`, `deferral`, `dependency`, `pattern`, `anti-pattern`, `mentioned`, `open-question`.

## Known caveats

- **Scraper-only writer.** Direct `telec memories save` calls from any agent other than the scraper are policy violations and should be flagged.
- **Predicate vocabulary is closed.** Free-form predicates are rejected at save. Vocabulary changes require a spec update.
- **No automatic retention.** Triples persist until explicit delete. Pattern-matchers may flag stale or contradicted triples for human review.
- **No interpretation.** The scraper records demonstrated facts. Synthesis is downstream.
- **General tier deferred.** Population-wide observations are not modeled in v1.
- **Doc-snippet dedup is mandatory.** Skipping it is the failure mode that turns memory into duplicate noise.
- **v1 storage shape may transition.** The existing `memory_observations` table carries `title`, `narrative`, `type`, `identity_key`, `project`, `facts`. v1 may map this to the triple model by convention (`subject ← identity_key | project`, `predicate ← title` or `type`, `object ← narrative`) until a schema migration adds explicit `tier`, `subject`, `predicate`, `object`, `source_session_id` columns. The externally visible scraper behavior is unchanged across the transition.
