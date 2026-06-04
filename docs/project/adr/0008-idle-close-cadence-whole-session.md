---
id: 'project/adr/0008-idle-close-cadence-whole-session'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '8'
date: '2026-05-21'
adr_status: 'accepted'
description: 'Memory extraction runs over the whole session delta on two triggers — idle ≥30 minutes or session close. Per-turn windowing (e.g., Hermes-style every-N-turns) is not used for memory.'
---

# ADR-0008: Idle/Close Cadence, Whole-Session Ingestion — ADR

## Context

The v2 architecture's transport-rules originally proposed per-session turn-trigger windowing (Hermes-style, ~10 turns) as a default cadence for `extract-window` consumers. That cadence makes sense for _active in-session_ skill harvesting, where short repetitive sequences are the signal. It does not match what memory extraction is doing.

Memory observations crystallize from sustained exchanges — decisions, frictions, requirements, preferences expressed over the course of a session. A 10-turn window is both too small (misses observations that span more turns) and too frequent (pays the LLM classification + doc-dedup cost N times for the same content).

We needed a cadence aligned with how observations actually surface.

## Decision

Memory extraction triggers on one of two conditions per session:

- **Idle threshold reached** — the session has been idle for ≥30 minutes since `last_activity`.
- **Session close** — the session has transitioned to closed/stopped.

Both triggers process the **whole session delta** since the last extraction (using `source_mirror_id` plus saved_at to determine the high-water mark). No windowing. No per-turn scanning.

The trigger handler is the daemon's maintenance loop; no separate scheduler entry is required. The per-session turn-trigger pathway in the v2 architecture is deliberately NOT used for memory.

## Consequences

**Positive:**

- The cadence matches how memory observations actually crystallize (over sustained exchanges, not micro-windows).
- LLM classification and doc-snippet dedup cost is paid once per session burst, not N times per session.
- The maintenance loop is already running — no new scheduler infrastructure for memory.
- Sessions that go idle and resume can still produce extraction across the resumption boundary (each idle-then-resume cycle gets its own extraction pass).

**Negative:**

- Memory is not "live" — observations from an active session don't appear until the session goes idle or closes. Acceptable: memory is the long-term substrate, not the per-turn working state.
- Idle threshold is a fixed value (30 min). If a session is genuinely idle but not closed, extraction runs even though more content may follow. This is fine — append-only semantics (ADR-0003) make repeated runs safe.
- The choice to override the v2 architecture's per-turn-trigger default for memory specifically means transport-rules.md must be clear that turn-trigger is optional, not the default for every consumer.

## Alternatives Considered

- **Hermes-style per-turn windowing (~10 turns).** Rejected: solves a different problem (active skill harvesting), pays extraction cost too often, misses observations that span longer windows.
- **Pure scheduler-tick cadence (every cron tick, scan all sessions).** Rejected as wasteful — most ticks would find nothing new and still pay the scan cost.
- **Event-driven (subscribe to session.idle and session.closed events).** Considered as the implementation mechanism for the chosen cadence. Acceptable; how the daemon detects the trigger is operational, not architectural. The decision here is the trigger conditions and the whole-session window, not the implementation pathway.
