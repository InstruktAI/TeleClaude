# DOR Report: integrator-wiring

## Assessment Summary

**Status:** Draft — pending formal gate validation.

The requirements and implementation plan have been updated to align with the
actual `teleclaude_events` API surface from `event-platform-core`. The previous
version referenced "notification service" / `NotificationProducer` terminology
that doesn't match the dependency's interface.

## Gate Analysis

### 1. Intent & Success

**Pass.** The problem statement is explicit: the integration module exists as a
fully-tested library with zero production consumers. The goal is clear: wire it
into the orchestration flow via the event platform, replace the inline
POST_COMPLETION merge, and eliminate bidirectional sync. Success criteria are
concrete and testable (7 verification requirements).

### 2. Scope & Size

**Pass with note.** The work is scoped to wiring — no integration module
internals change. Seven phases, each independently committable. The scope is
substantial but atomic to the finalize-and-merge path. Cross-cutting concern:
the integration trigger cartridge lives in `teleclaude_events` (the dependency
package), not in `teleclaude/`. This is the correct location (cartridges belong
to the pipeline runtime) but the builder must be aware of the package boundary.

### 3. Verification

**Pass.** End-to-end tests, notification lifecycle tests, regression tests, and
cutover enforcement tests are defined. Demo artifact has executable validation
blocks.

### 4. Approach Known

**Pass.** The integration module's internals are delivered and tested. The event
platform's cartridge interface is defined. The bridge pattern (thin adapter
between orchestration lifecycle and event emission) is straightforward. The
trigger cartridge pattern follows existing cartridge implementations (dedup,
notification projector).

### 5. Research Complete

**Pass.** No new third-party dependencies. The event platform (`teleclaude_events`)
is an internal dependency with a defined API surface from `event-platform-core`
requirements and implementation plan.

### 6. Dependencies & Preconditions

**Pass.** `event-platform-core` is the single dependency. It has DOR score 8
(pass) and is in the roadmap with `integrator-wiring` declared as `after:
[event-platform-core]`. The dependency's API surface (EventProducer, emit_event,
EventCatalog, EventSchema, NotificationLifecycle, cartridge interface,
PipelineContext) is documented in its requirements and implementation plan.

### 7. Integration Safety

**Pass.** The change can be merged incrementally — event schemas first, then
emission wiring, then trigger, then POST_COMPLETION replacement, then cutover.
Rollback: disable cutover env vars to revert to old inline flow.

### 8. Tooling Impact

**N/A.** No scaffolding or tooling changes.

## Interface Alignment (Draft Correction)

The following naming corrections were applied during this draft:

| Previous (incorrect)                              | Corrected                                                  |
| ------------------------------------------------- | ---------------------------------------------------------- |
| `NotificationProducer.emit()`                     | `emit_event()` / `EventProducer`                           |
| "notification service event catalog"              | `EventCatalog` with `EventSchema` registration             |
| `teleclaude_notifications/schemas/...`            | `teleclaude_events/schemas/software_development.py`        |
| "notification processor callback"                 | Integration trigger cartridge in pipeline chain            |
| "notification service's contract"                 | Event platform's contract (`teleclaude_events`)            |

## Open Questions

1. **Cartridge placement:** The integration trigger cartridge processes events
   to feed the readiness projection. Should it run before or after the
   notification projector? It doesn't modify events — it only reads them and
   triggers side effects. Running after dedup but alongside/before the
   notification projector seems correct. The gate should confirm.

2. **PipelineContext extension:** The trigger cartridge needs access to the
   daemon's session management (to spawn integrator sessions) and the
   `ReadinessProjection` instance. These may need to be added to
   `PipelineContext` or provided via a callback. The event-platform-core's
   `PipelineContext` currently provides: event catalog, notification DB handle,
   push callback. A daemon callback may need to be added.

## Assumptions

1. The `teleclaude_events` package will expose its catalog registration as
   extensible (either via `build_default_catalog()` including integration
   schemas, or via a `register_integration_schemas(catalog)` entry point).
2. The cartridge interface (`async def process(event, context)`) is stable
   and won't change before this todo is built.
3. `PipelineContext` can be extended with daemon callbacks without breaking
   existing cartridges.
