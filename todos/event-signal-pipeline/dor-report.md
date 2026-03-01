# DOR Report: event-signal-pipeline

## Assessment Summary

Draft DOR assessment for the three-stage signal pipeline (ingest, cluster, synthesize).
Artifacts are detailed and codebase-aligned. Primary open item is the dependency chain.

## Gate Analysis

### 1. Intent & Success

**Status: Pass**

Problem statement is explicit: pull raw content from external feeds, normalise into event
envelopes, cluster related items, synthesise structured artifacts. Success criteria are
concrete and testable (12 items, each with observable outcomes). The "what" and "why" are
captured in both `input.md` and `requirements.md`.

### 2. Scope & Size

**Status: Needs attention**

The plan has 8 phases with ~20 tasks. This is large for a single AI session. However:
- Phases are independent and can be committed incrementally.
- Each phase produces a testable artifact.
- The plan is structured for commit-per-phase, which allows the builder to checkpoint.

Recommendation: assess whether breakdown into sub-todos is warranted. The plan is linear
(schema → storage → ingest → cluster → synthesize → wiring → tests → review) so
sequential single-session execution is viable if context limits hold.

### 3. Verification

**Status: Pass**

Phase 7 defines comprehensive unit tests for each cartridge and utility module. Success
criteria include `make test` and `make lint`. Demo.md provides runtime validation steps.
Edge cases (dedup, burst detection, novelty, singleton promotion, embedding fallback) are
identified.

### 4. Approach Known

**Status: Pass**

The implementation plan references concrete codebase patterns with file locations:
- `Cartridge` Protocol in `teleclaude_events/pipeline.py`
- `EventEnvelope` in `teleclaude_events/envelope.py`
- `EventSchema` + `register_all()` in `teleclaude_events/schemas/`
- `EventDB` patterns in `teleclaude_events/db.py`
- Background task hosting in `teleclaude/daemon.py`

All referenced patterns exist in the codebase. No architectural unknowns remain.

### 5. Research Complete

**Status: Pass (no third-party dependencies)**

All dependencies are stdlib or already in the project:
- `xml.etree.ElementTree` (stdlib) for RSS/OPML parsing
- `aiohttp` for HTTP fetches (already a project dependency)
- `aiosqlite` for storage (already used by EventDB)
- `pydantic` for models (already used throughout)

### 6. Dependencies & Preconditions

**Status: Needs attention — dependency not delivered**

Roadmap declares `after: [event-domain-infrastructure]`. That todo is `build: pending`,
`dor.score: 0`. The implementation plan lists three prerequisites:

1. `teleclaude_events/` package exists — **delivered** (event-platform core)
2. `PipelineContext` extensible with AI client — **not yet** (domain-infrastructure adds this)
3. `company/cartridges/` loader operational — **not yet** (domain-infrastructure defines this)

However, the signal pipeline plan (Phase 6, Task 6.1) self-contains the `PipelineContext`
extension (adds `ai_client` and `emit` fields). And Phase 1 Task 1.1 creates the
`company/cartridges/` directory. The loader wiring (Task 6.3) references domain-infrastructure's
cartridge loader but could potentially be simplified to direct registration if the loader
doesn't exist yet.

**Key question for gate:** Can this todo's plan proceed independently of domain-infrastructure,
or does the cartridge loader mechanism create a hard coupling?

### 7. Integration Safety

**Status: Pass**

The plan is additive — new files in `company/cartridges/signal/`,
`teleclaude_events/signal/`, `teleclaude_events/schemas/signal.py`. Extensions to
`PipelineContext` add optional fields (backward-compatible). The only modification to
existing code is in `teleclaude_events/schemas/__init__.py` (add signal schema registration)
and `teleclaude/daemon.py` (startup wiring). Both are incremental additions.

### 8. Tooling Impact

**Status: N/A** — No tooling or scaffolding changes.

## Open Questions

1. **Dependency gap**: `event-domain-infrastructure` is pending. The plan references its
   cartridge loader (Task 6.3). Should the signal pipeline self-contain a minimal loader,
   or should it wait for domain-infrastructure to deliver first?
2. **Scope atomicity**: 8 phases / ~20 tasks approaches single-session limits. Should this
   be split into sub-todos (e.g., signal-ingest, signal-cluster, signal-synthesize)?
3. **`company/cartridges/` path vs domain-infrastructure paths**: The plan uses in-repo
   `company/cartridges/signal/` while domain-infrastructure defines runtime discovery at
   `~/.teleclaude/company/domains/{name}/cartridges/`. Clarify which model applies.

## Assumptions

- The builder will verify prerequisites at the start of Phase 1 and adapt if
  domain-infrastructure artifacts are not yet available.
- `PipelineContext` extension (Phase 6, Task 6.1) is safe because it adds optional fields
  only.
- Signal tables co-locate in `~/.teleclaude/events.db` (same file as EventDB).
