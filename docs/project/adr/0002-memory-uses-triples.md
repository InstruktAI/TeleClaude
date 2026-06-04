---
id: 'project/adr/0002-memory-uses-triples'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '2'
date: '2026-05-21'
adr_status: 'accepted'
description: 'Memory observations are stored as (subject, predicate, object) triples rather than as flat title+narrative+type records.'
---

# ADR-0002: Memory Uses Triples — ADR

## Context

The pre-existing memory model carried observations as flat records with `title`, `narrative` (free-text body), and a single `type` field selecting from a closed seven-value taxonomy (preference, decision, discovery, gotcha, pattern, friction, context). Reasonable for an initial implementation, but produced two compounding problems as we scoped the v2 memory pillar: (1) querying "what does this human prefer about X" required free-text search rather than structured lookup, and (2) downstream pattern-matchers (Tier 2 consumers reading accumulated memory) had to LLM-classify every record to group anything meaningfully.

We needed a data shape that supported structured queries (subject + predicate filter), structured aggregation by predicate (e.g., "all requirements for project teleclaude"), and dedup against existing records by composite key — without requiring an LLM in the read path.

## Decision

Memory observations are stored as `(subject, predicate, object)` triples plus provenance and timestamp metadata. The triple is the atomic unit. The predicate is drawn from a per-category controlled vocabulary (defined in `feature/memory/extraction-human` and `feature/memory/extraction-project`). The object is free-form text. The subject is opaque-stringly typed: an email or identity-context string for human-category, a project slug for project-category.

The free-text `title` and `narrative` fields are dropped; the object field carries the semantic payload directly.

## Consequences

**Positive:**

- Structured queries become natural: `SELECT WHERE subject=X AND predicate=Y` without LLM-in-the-read-path.
- Aggregation by predicate is a SQL `GROUP BY`, not an LLM classification pass.
- Dedup against `(subject, predicate, object)` becomes a uniform pattern across all consumers.
- The data shape can carry both human-tier and project-tier observations through one store with category-specific vocabularies.

**Negative:**

- Loss of free-text title/narrative nuance. Complex observations must be either fit into a single object field (text) or split into multiple atomic triples.
- The controlled predicate vocabulary is a maintenance surface — adding or renaming predicates requires a feature-spec update.
- v1 data carrying title+narrative+type doesn't map cleanly into triples; cutover requires translation (handled by v2-memory-cutover).

## Alternatives Considered

- **Keep the v1 shape.** Rejected because of the LLM-in-the-read-path problem; querying memory in any structured way required interpretive synthesis at every read.
- **Property-graph (nodes + edges + properties).** Rejected as over-engineered for our actual query patterns. Graph queries (cross-triple co-occurrence) are not a primary use case; the rare time we need them, joins on the triple store suffice.
- **Triples with frequency counters and evidence blobs.** Considered (and briefly proposed) for representing salience and per-occurrence context. Rejected in favor of pure append-only event-store semantics (see ADR-0003) — counter-and-blob produces merge logic at write time, whereas append-only lets downstream aggregation do the salience math at read time with no merge.
