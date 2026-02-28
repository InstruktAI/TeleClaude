# DOR Report: integrator-wiring

## Assessment Summary

**Status:** Pass — formal gate validation complete.
**Score:** 8/10
**Gate Date:** 2026-02-28

All eight DOR gates pass. The artifacts are well-structured, codebase-aligned, and
the dependency (`event-platform-core`, DOR score 8) is correctly sequenced. Two
open questions from the draft phase are resolved below as implementation guidance
rather than blockers.

## Gate Analysis

### 1. Intent & Success

**Pass.** The problem statement is explicit: the integration module exists as a
fully-tested library with zero production consumers. The goal is clear: wire it
into the orchestration flow via the event platform, replace the inline
POST_COMPLETION merge, and eliminate bidirectional sync. Success criteria are
concrete and testable (7 verification requirements in requirements.md).

### 2. Scope & Size

**Pass.** The work is scoped to wiring — no integration module internals change.
Seven phases, each independently committable. The scope is substantial but atomic
to the finalize-and-merge path. Cross-cutting concern acknowledged: the integration
trigger cartridge lives in `teleclaude_events` (not `teleclaude/`). This is correct
— cartridges belong to the pipeline runtime — but the builder must respect the
one-way dependency: `teleclaude_events` must not import from `teleclaude`. The
daemon callback injection via `PipelineContext` preserves this boundary.

### 3. Verification

**Pass.** Seven verification requirements defined. End-to-end tests (Task 6.1),
notification lifecycle tests (Task 6.2), and regression tests (Task 6.3) cover
the critical paths. Demo artifact has 9 executable validation blocks. Cutover
enforcement is explicitly tested.

### 4. Approach Known

**Pass.** All referenced code entities verified in codebase:
- POST_COMPLETION inline merge steps: `core.py:223-267` (12-step sequence confirmed)
- `sync_slug_todo_from_worktree_to_main`: `core.py:1986`
- `sync_slug_todo_from_main_to_worktree`: `core.py:2005`
- Call site: `core.py:2945`
- `IntegratorShadowRuntime`: `runtime.py:205`
- `ReadinessProjection`: `readiness_projection.py:62`
- `IntegrationEventStore`: `event_store.py:32`
- `IntegrationEventService`: `service.py:39`
- `IntegratorCutoverControls`: `authorization.py:14`
- `CanonicalMainPusher`: `runtime.py:38`

The bridge pattern (thin adapter between orchestration lifecycle and event emission)
is straightforward. The trigger cartridge follows existing cartridge patterns (dedup,
notification projector) from the event-platform-core plan.

### 5. Research Complete

**Pass.** No new third-party dependencies. The event platform (`teleclaude_events`)
is an internal dependency with a fully documented API surface from the
`event-platform-core` requirements and implementation plan.

### 6. Dependencies & Preconditions

**Pass.** `event-platform-core` is the single dependency:
- DOR score: 8 (pass) — confirmed in `todos/event-platform-core/state.yaml`
- Roadmap: `integrator-wiring` declared `after: [event-platform-core]` — confirmed
- API surface documented: `EventProducer`, `emit_event()`, `EventCatalog`,
  `EventSchema`, `NotificationLifecycle`, `Cartridge` protocol, `PipelineContext`,
  `Pipeline`, `EventProcessor`

No new configuration keys introduced (cutover env vars already exist in the
integration module).

### 7. Integration Safety

**Pass.** Incremental merge path: schemas → emission → trigger → POST_COMPLETION
replacement → cutover → cleanup. Rollback: disable `TELECLAUDE_INTEGRATOR_CUTOVER_ENABLED`
to revert to the old inline flow. Each phase is independently committable and testable.

### 8. Tooling Impact

**N/A.** No scaffolding or tooling changes.

## Plan-to-Requirement Fidelity

| Requirement | Plan Coverage | Status |
| ----------- | ------------- | ------ |
| FR1: Integration Event Schemas | Phase 1, Task 1.1 | Aligned |
| FR2: Event Emission | Phase 2, Tasks 2.1-2.3 | Aligned |
| FR3: Integrator Trigger | Phase 3, Tasks 3.1-3.2 | Aligned |
| FR4: POST_COMPLETION Replacement | Phase 4, Task 4.1 | Aligned |
| FR5: Integrator Session Contract | Phase 3, Task 3.3 | Aligned |
| FR6: Cutover Activation | Phase 5, Task 5.1 | Aligned |
| FR7: Replace File-Based Event Store | Phase 5, Task 5.2 | Aligned |
| FR8: Eliminate Bidirectional Sync | Phase 5, Task 5.3 | Aligned |

No contradictions found between plan and requirements. No plan task prescribes
behavior that contradicts a requirement.

## Open Questions Resolved

### 1. Cartridge placement (from draft)

**Resolved.** The integration trigger cartridge reads events and triggers side
effects (readiness projection feed + integrator spawn) but does not modify events.
It should run after the dedup cartridge (to avoid processing duplicates) and before
or alongside the notification projector (ordering between them is irrelevant since
neither depends on the other's output). The builder should place it between dedup
and notification projector in the cartridge chain.

### 2. PipelineContext extension (from draft)

**Resolved.** The trigger cartridge needs a daemon callback to spawn integrator
sessions and a `ReadinessProjection` instance. The `PipelineContext` dataclass
from event-platform-core can be extended with additional fields without breaking
existing cartridges (dataclass allows new optional fields). The daemon injects
these when constructing the pipeline context — this preserves the `teleclaude_events`
→ `teleclaude` dependency boundary (no imports, only injected callbacks).

## Assumptions (Validated)

1. `teleclaude_events` catalog registration is extensible — confirmed from
   event-platform-core plan: `build_default_catalog()` with `register_all(catalog)`
   pattern in `teleclaude_events/schemas/__init__.py`.
2. Cartridge interface (`async def process(event, context)`) — confirmed stable
   from event-platform-core requirements and plan.
3. `PipelineContext` extension — dataclass with injection, confirmed compatible.

## Interface Alignment (Draft Correction)

The following naming corrections were applied during the draft phase:

| Previous (incorrect)                              | Corrected                                                  |
| ------------------------------------------------- | ---------------------------------------------------------- |
| `NotificationProducer.emit()`                     | `emit_event()` / `EventProducer`                           |
| "notification service event catalog"              | `EventCatalog` with `EventSchema` registration             |
| `teleclaude_notifications/schemas/...`            | `teleclaude_events/schemas/software_development.py`        |
| "notification processor callback"                 | Integration trigger cartridge in pipeline chain            |
| "notification service's contract"                 | Event platform's contract (`teleclaude_events`)            |

## Gate Verdict

**PASS** — score 8/10. All gates satisfied. Dependency is sequenced and assessed.
Artifacts are implementation-ready pending `event-platform-core` delivery.
