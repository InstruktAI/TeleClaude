---
id: 'project/adr/0005-scraper-only-memory-writer'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '5'
date: '2026-05-21'
adr_status: 'accepted'
description: 'Memory is writable exclusively by the dedicated memory extraction agents (the scrapers). All other agents are prohibited from calling telec memories save.'
---
# ADR-0005: Scraper-Only Memory Writer — ADR

## Context

The pre-existing memory model allowed any agent or human to call `telec memories save`. The intent was that agents could spot and record observations as they went. In practice this produced two failure modes:

- Agents recorded their own running thoughts as memory ("I noticed the user prefers X"), polluting the store with interpretation and self-reference instead of durable facts about the human or the project.
- The dedup-against-docs discipline (ADR-0006) became unenforceable in practice — every agent would need to apply it every time it saved, and the discipline rotted quickly under load.

We needed memory writes to come from a small number of well-instructed agents whose only job is extraction, dedup, and classification — so the discipline can be enforced cleanly.

## Decision

Memory is writable exclusively by the dedicated memory extraction agents (the scrapers — currently the human-category and project-category miners). All other agents are prohibited from calling `telec memories save`. The `telec memories save` CLI surface is hidden from default help; its desc explicitly identifies the scrapers as its only sanctioned callers.

The scrapers are invoked via dedicated slash commands (e.g., `/extract-memory-human <session_id>`) and follow the memory-extraction procedure family. They are the only writers.

## Consequences

**Positive:**

- Memory discipline (dedup against docs, no interpretation, no synthesis) is enforced in two well-instructed agents instead of every agent that touches the system.
- The memory store stays clean: no agent self-reference, no running commentary, no interpretation-as-fact.
- Future write-path enforcement (e.g., refusing saves from non-scraper callers at the CLI or API layer) is a small change because the policy is already in place.

**Negative:**

- An agent observing something memory-worthy in flight cannot record it directly; the observation lives only in the session transcript and is picked up later by the scraper. Some signal latency.
- The slash command + scraper-agent setup is more infrastructure than a "call this CLI command" pattern. Heavier per-extraction.
- Errors in the scraper procedure produce silent gaps in memory accumulation that other agents can't backfill.

## Alternatives Considered

- **Any agent writes; trust the discipline.** The previous status quo. Rejected because trust-the-discipline doesn't scale across heterogeneous agents.
- **A write-time validator that enforces the dedup rule on every save regardless of caller.** Considered. Rejected because the dedup rule requires LLM judgment (substantive coverage in docs), not a structural check; a validator can't enforce it. The discipline lives in the procedure, not in the storage layer.
- **Two-tier writers: scraper for batch, agents for ad-hoc.** Rejected because the two write paths would drift in discipline and the ad-hoc path would become a leak.