---
adr_status: 'accepted'
date: '2026-05-21'
description: 'Memory observations carry source_mirror_id as their provenance handle. Mirrors are eternal, so the pointer never rots; TeleClaude session_ids are ephemeral and native CLI session UUIDs are CLI-controlled.'
number: '7'
visibility: 'public'
---

# ADR-0007: Provenance via mirror_id — ADR

## Context

Every memory observation needs a provenance handle — a way to point back to the source it was extracted from, so future agents can verify the observation, understand its context, or detect data quality issues.

Three candidate handles were on the table:

- **TeleClaude `session_id`.** Convenient but ephemeral: the daemon evicts session records after the operational window, so the pointer can dangle.
- **Native CLI `native_session_id`.** Controlled by the agent CLI (Claude Code, Codex, Gemini); the CLI may prune the underlying transcript files per its own retention policy. The pointer can dangle if the CLI prunes.
- **Session mirror `mirror_id`.** Eternal by design — mirrors are decoupled from both the TeleClaude session record and the native CLI transcript file (see `session_mirrors` domain spec). The pointer never goes stale as long as the mirror exists, which is "forever."

We needed the handle that never rots.

## Decision

Memory observations carry `source_mirror_id` as their provenance handle. The scraper reads the session record to resolve which mirror corresponds to the session being extracted, then records that `mirror_id` on every saved triple.

`session_id` (TeleClaude) and `native_session_id` (CLI) do NOT appear on memory rows. They are operational handles used at extraction time to find the mirror; they are not stored as provenance.

## Consequences

**Positive:**

- Provenance never rots. As long as session_mirrors persists its data (its design says "eternal"), every memory row remains traceable to its source.
- One canonical handle: future consumers don't need to disambiguate "is this a TeleClaude id or a native CLI id?" — it's always a mirror_id.
- The scraper reads from `session_mirrors.text_content` for its transcript source, so the same mirror_id is the input AND the provenance — no separate lookup.

**Negative:**

- The session_mirrors pillar becomes a hard dependency for memory. If session_mirrors is unavailable, memory loses its provenance bridge.
- mirror_id is a UUID, not human-readable. Operators inspecting memory rows can't immediately tell which session a triple came from without a join.
- Migrating v1 memory rows (which carry whatever they currently carry as provenance — likely `session_id` or similar) into the v2 triple shape with mirror_id requires resolving each v1 row's source mirror.

## Alternatives Considered

- **session_id (TeleClaude).** Rejected: ephemeral.
- **native_session_id.** Rejected: CLI-controlled retention, can disappear.
- **transcript file path.** Rejected: path can move; CLI can prune; not stable.
- **A composite handle (agent + native_session_id + saved_at).** Considered as a fallback for cases where no mirror exists yet. Rejected because mirrors are built incrementally and always exist by the time the scraper runs (the scraper triggers on idle or close, both of which happen after at least one mirror update).
