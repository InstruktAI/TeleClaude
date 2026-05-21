---
id: 'project/adr/0006-mandatory-dedup-against-doc-snippets'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '6'
date: '2026-05-21'
adr_status: 'accepted'
description: 'Before saving any memory triple, the scraper must search existing doc snippets for substantive coverage and discard candidates that are already codified. Codified knowledge does not get re-encoded as memory.'
---
# ADR-0006: Mandatory Dedup Against Doc Snippets — ADR

## Context

Memory and the doc-snippet library both store knowledge the platform draws on. Without a discipline keeping them apart, they drift: the same fact ends up in both places, in different wording, with no clear authority. Future agents reading either store get conflicting signals; eventually neither is trustworthy.

The original memory model had no dedup discipline at all — any agent could save anything. Doc snippets were the codified library; memory was the dynamic store; nothing connected them. Over time, memory would accumulate facts that were already in doc snippets, with worse precision and no review.

We needed a rule that keeps memory from becoming a duplicate junk drawer next to the codified library — without conflating the two systems.

## Decision

Before saving any memory triple, the scraper MUST search existing doc snippets (`telec docs index` + `telec docs get`) for substantive coverage of the candidate. If the candidate is substantively covered — even with different wording — the candidate is discarded. Memory does not re-encode codified knowledge.

This is a write-time discipline applied in Phase B of the memory-extraction procedure. It is not a structural check (no validator can enforce "substantively the same"); it is an LLM-judgment step in the scraper's procedure.

The reverse direction (dedup memory rows against each other) is explicitly NOT a write-time discipline — see ADR-0003 (event-store semantics). Repeated observations within memory are meaningful for salience.

## Consequences

**Positive:**

- Memory and doc snippets stay differentiated: codified knowledge in docs (authoritative, reviewed, public); extracted observations in memory (dynamic, accumulated, per-subject).
- Future agents reading memory know it complements docs rather than duplicating them.
- The "what's authoritative?" question has a clear answer: if it's in docs, that's authoritative; memory is the running record of what's been observed, not what's been decided.

**Negative:**

- Every save incurs a doc-snippet search cost (LLM-judgment over `telec docs index` results). Slower than a no-dedup save.
- The discipline is intelligence-enforced; a sloppy scraper would skip it. Hence ADR-0005 (scraper-only writer) — restricting writes to a small set of well-instructed agents.
- "Substantively covered" is a judgment call. Edge cases will produce false positives (memory loss) and false negatives (duplicate noise). The bias should be toward false positives — losing a memory is cheaper than polluting the store.

## Alternatives Considered

- **No dedup discipline.** The previous status quo. Rejected because of the inevitable duplication-and-drift failure.
- **Two-way dedup: memory→docs AND memory→memory at write time.** Considered. Rejected because memory→memory dedup destroys the salience signal that frequency provides (per ADR-0003). Only one direction (memory→docs) is enforced.
- **Hard-link memory rows to doc snippets when overlap is detected.** Considered. Rejected as over-engineered: the simple rule is "discard if covered"; introducing a link would require schema changes and ongoing maintenance with no clear consumer.