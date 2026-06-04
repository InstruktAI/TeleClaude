---
id: 'project/adr/0003-memory-event-store-semantics'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '3'
date: '2026-05-21'
adr_status: 'accepted'
description: 'Memory writes are append-only — multiple rows with the same (subject, predicate, object) are allowed. Dedup is a read-time concern for downstream consumers, not a write-time check.'
---

# ADR-0003: Memory Event-Store Semantics — ADR

## Context

Once triples were chosen as the data shape (ADR-0002), an immediate design question was: what does the store do when the scraper tries to save a triple that already exists? Two main options were on the table — a deduplicated knowledge graph (each `(subject, predicate, object)` exists at most once, with a frequency counter advanced on repeats) or an event-store (every save appends a new row; aggregation happens downstream at read time).

The dedup-on-write approach needed a frequency counter, an evidence blob to accumulate per-occurrence context, and a read-before-write step on every save (search the store for an existing key, increment if found, insert if not). The append-only approach needed none of those — every save is a single insert; aggregation is a downstream `GROUP BY (subject, predicate, object)` with `COUNT(*)` for salience.

## Decision

The memory store uses **append-only event-store semantics.**

- Every save inserts a new row, regardless of whether `(subject, predicate, object)` already exists.
- No write-time dedup against existing memory rows. No frequency counter on the row.
- No evidence blob — provenance is the source `mirror_id`; if context is wanted, downstream consumers read the mirror.
- Salience is derived by downstream consumers via `GROUP BY (subject, predicate, object), COUNT(*)`.
- Project-category rows MAY be pruned by downstream pattern-matcher jobs after promotion into project artifacts; human-category rows persist indefinitely.

The single write-time dedup discipline that DOES apply: dedup against the codified library (doc snippets). See ADR-0006.

## Consequences

**Positive:**

- The write path is dead simple: insert one row, emit one event. No search-then-merge logic on the hot path.
- Re-runs of the scraper are safe by construction. A re-extraction produces duplicate rows that signal salience to downstream — no special idempotency logic needed.
- Per-occurrence provenance is preserved: each row carries its own `source_mirror_id`. If a downstream consumer wants to understand variation, it reads the mirrors directly.
- Schema is minimal. No counter column, no JSON blob column, no merge logic.

**Negative:**

- Storage grows linearly with extraction activity. Rows that repeat the same triple accumulate. For project-category data this is fine because rows get pruned downstream; for human-category data the row count is bounded by the human's actual conversation volume (small in practice).
- Querying "what does this human prefer" returns multiple rows of the same triple if the human stated it many times. Consumers must aggregate at read time.
- An empty extraction window (scraper ran, found nothing) doesn't advance any explicit marker — the high-water mark is implicit in the `MAX(saved_at)` over rows with that `source_mirror_id`. Re-running on the same window re-incurs the LLM classification cost but produces no harm.

## Alternatives Considered

- **Dedup-on-write with counter.** Considered. Rejected because the per-write search-then-merge step adds latency and complexity for no value that read-time aggregation doesn't already provide. Also the counter doesn't preserve per-occurrence provenance (the merge collapses provenance across hits).
- **Dedup-on-write with counter AND evidence blob.** Considered. Rejected as over-engineered: the evidence blob became a parallel sub-system (sampling, retention, merge rules) for a use case (downstream provenance) that the source mirror already covers.
- **Append-only AND a separate `extraction_markers` table** for high-water-mark bookkeeping. Considered. Rejected as redundant: the rows themselves carry `source_mirror_id` and `saved_at`, which together provide the marker by query.
