---
id: 'project/adr/0004-two-memory-categories'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '4'
date: '2026-05-21'
adr_status: 'accepted'
description: 'Memory observations are classified into exactly two categories — human (about a person) and project (about a project). A third "general" category was considered and deferred for lack of a concrete use case.'
---
# ADR-0004: Two Memory Categories — ADR

## Context

When designing how memory triples would be classified, we needed an axis that:

- Naturally splits the corpus by subject (whose facts are these about?)
- Maps cleanly to the downstream consumers (per-human context injection vs. per-project pattern matching)
- Survives the multi-tenant case (multiple humans sharing a project, multiple projects shared across humans)

Three candidate axes surfaced: by-human, by-project, and "general" (population-wide observations not tied to any specific human or project). The third tier was tempting — it would catch observations about how AI-human partnerships work in general, about systemic patterns across all sessions, about cross-cutting knowledge. But every concrete use case we tried to construct for it either collapsed back into project memory (TeleClaude is a project, observations about it go to the TeleClaude project tier), into human memory (preferences belong to a human), or into a future skill-detection capability (patterns of behavior, not facts).

## Decision

Memory uses exactly two categories:

- **`human`** — observations about a specific person. Subject is the person's durable identifier (email or identity-context string).
- **`project`** — observations about a specific project. Subject is the project slug.

The "general" category is **not** modeled in v2. If a concrete use case emerges that fits neither human nor project, we'll add it then — adding a category later is cheap; over-designing the taxonomy now is expensive.

The two categories have distinct predicate vocabularies (per the feature specs) and distinct downstream consumers (human → context injection at session start; project → pattern matchers producing todos/doc drafts).

## Consequences

**Positive:**

- The category axis is decisive: every candidate observation maps to exactly one category by asking "what is this *about*?"
- Multi-tenant works naturally: per-project memory aggregates across all humans in the project; per-human memory follows the human across all projects.
- The two-category model has clear downstream consumers, validating the split.

**Negative:**

- Observations that genuinely don't fit either category (rare in practice) must be discarded. The temptation to default to "general" doesn't exist — there's nowhere for them to go.
- A future "general" category, if added, requires a new vocabulary and new downstream consumers — design work deferred but not eliminated.

## Alternatives Considered

- **Three categories (human / project / general).** Considered. Rejected because no concrete general-tier use case survived scrutiny — every example collapsed into one of the other two or into future skill detection.
- **One category, free-form subject.** Considered. Rejected because the downstream consumer needs to know whether a subject is a person or a project to render it correctly. Encoding that in a free-form string would push parsing burden onto every consumer.
- **N categories, one per pillar.** Considered. Rejected as over-fragmented; most pillars don't accumulate observations the way memory does (the memory pillar IS the pillar that accumulates observations; other pillars own their own state).