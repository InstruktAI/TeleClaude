# DOR Report: event-signal-pipeline

## Gate Verdict: PASS (score 8)

Three-stage signal pipeline (ingest, cluster, synthesize) is ready for implementation.
Artifacts are detailed, codebase-verified, and internally consistent after gate tightening.
The dependency on `event-domain-infrastructure` is deferred — the plan self-contains all
needed infrastructure via direct `Pipeline` registration and `PipelineContext` extension.

## Gate Analysis

### 1. Intent & Success — PASS

Problem statement is explicit: pull raw content from external feeds, normalise into event
envelopes, cluster related items, synthesise structured artifacts. Twelve success criteria
are concrete and testable with observable outcomes. The "what" and "why" are captured in
both `input.md` and `requirements.md`.

### 2. Scope & Size — PASS (with note)

The plan has 8 phases with ~20 tasks. This is large for a single AI session. Mitigating factors:
- Phases are linearly ordered with clean boundaries.
- Each phase produces independently testable, committable artifacts.
- Commit-per-phase structure enables checkpoint recovery.
- No circular dependencies between phases.

**Builder guidance:** If context pressure builds during later phases (5+), consider splitting
the remaining work into a continuation session. The checkpoint structure supports this.

### 3. Verification — PASS

Phase 7 defines comprehensive unit tests for each cartridge and utility module. Success
criteria include `make test` and `make lint`. `demo.md` provides 8 executable validation
blocks covering schema registration, imports, config, DB tables, RSS parsing, import
boundaries, tests, and lint. Edge cases identified: dedup, burst detection, novelty,
singleton promotion, embedding fallback.

### 4. Approach Known — PASS

All codebase references verified against current `main`:

| Pattern                 | File                                    | Verified |
| ----------------------- | --------------------------------------- | -------- |
| `Cartridge` Protocol    | `teleclaude_events/pipeline.py:20`      | Yes      |
| `PipelineContext`       | `teleclaude_events/pipeline.py:14`      | Yes      |
| `EventEnvelope`         | `teleclaude_events/envelope.py:32`      | Yes      |
| `register_all()`        | `teleclaude_events/schemas/__init__.py:11` | Yes   |
| `EventDB` + aiosqlite   | `teleclaude_events/db.py`              | Yes      |
| `EventLevel` enum       | `teleclaude_events/envelope.py:19`      | Yes      |
| `EventVisibility` enum  | `teleclaude_events/envelope.py:13`      | Yes      |

`PipelineContext` currently has `catalog`, `db`, and `push_callbacks` fields. The plan
adds optional `ai_client` and `emit` fields (Task 6.1) — backward-compatible with existing
cartridges.

**Architectural note:** The current `Pipeline.execute()` is 1:1 (one event in → one event or
None out). The signal pipeline needs 1:N capability (ingest consumes a trigger, emits N items).
The `emit` callback on `PipelineContext` is the escape hatch — cartridges emit events through
it and return `None` from `process()`. This pattern is sound and well-documented in the plan.

### 5. Research Complete — PASS (no third-party dependencies)

All dependencies are stdlib or already in the project:
- `xml.etree.ElementTree` (stdlib) for RSS/OPML parsing
- `aiohttp` for HTTP fetches (existing project dependency)
- `aiosqlite` for storage (existing — used by `EventDB`)
- `pydantic` for models (existing — used throughout)

### 6. Dependencies & Preconditions — PASS (deferred integration)

Roadmap declares `after: [event-domain-infrastructure]`. That todo is `build: pending`,
`dor.score: 0`, itself blocked by `event-system-cartridges`.

**Resolution:** The plan self-contains all needed infrastructure:
- Task 1.1: Creates `company/cartridges/` package scaffolding.
- Task 6.1: Extends `PipelineContext` with optional `ai_client` and `emit` fields.
- Task 6.3: Registers cartridges directly with `Pipeline` (not via domain-infrastructure loader).

When `event-domain-infrastructure` ships, the registration migrates to its discovery mechanism.
The cartridge code itself is unchanged — only the wiring in `daemon.py` adapts.

**Deferred:** Domain-infrastructure cartridge loader integration. Documented in requirements
and plan. Non-blocking for build.

### 7. Integration Safety — PASS

The change is additive:
- New files: `company/cartridges/signal/`, `teleclaude_events/signal/`, `teleclaude_events/schemas/signal.py`
- Extensions: `PipelineContext` gets optional fields (no breakage)
- Modifications: `teleclaude_events/schemas/__init__.py` (add signal registration), `teleclaude/daemon.py` (startup wiring)

Both modifications are incremental additions to existing patterns.

### 8. Tooling Impact — N/A

No tooling or scaffolding changes.

## Gate Actions Taken

1. **Fixed `emit_batch` → `emit` inconsistency** in implementation-plan.md Task 3.2.
   Task 6.1 defines `emit: Callable`, not `emit_batch`. Plan now uses `context.emit()` consistently.
2. **Replaced domain-infrastructure loader reference** in implementation-plan.md Task 6.3
   with direct `Pipeline` registration and a deferred migration note.
3. **Updated success criterion** in requirements.md from "loadable via the domain-infrastructure
   cartridge loader" to "loadable via direct Pipeline registration."
4. **Clarified cartridge path model** in requirements.md: in-repo source code path now, runtime
   discovery path when domain-infrastructure ships.

## Remaining Assumptions

- The builder will verify `PipelineContext` field additions don't break existing cartridges
  (dedup, notification projector) during Phase 6.
- Signal tables co-locate in `~/.teleclaude/events.db` (same file as `EventDB`).
- The `emit` callback will be wired by the daemon to re-enter the pipeline processor (so
  emitted events flow through subsequent cartridges). The exact wiring is a builder concern.

## Deferrals

- Domain-infrastructure cartridge loader integration (→ `event-domain-infrastructure`)
- Runtime discovery at `~/.teleclaude/company/domains/signal/cartridges/` (→ `event-domain-infrastructure`)
- `telec signals status` CLI (marked optional/low priority in requirements)
