# DOR Report: integration-event-chain-phase2

## Gate Assessment

### 1. Intent & Success — PASS

The problem statement is explicit: complete the three-event integration gate by wiring the
readiness projection into the cartridge, removing legacy lock serialization. Success criteria
are concrete and mechanically verifiable (function removal, event schema registration, test pass).

### 2. Scope & Size — PASS (with note)

The work spans four files for wiring (event schema, bridge, cartridge, daemon) and four files
for removal (core.py, todo_routes.py, session_cleanup.py, POST_COMPLETION). This fits a single
AI session. The inclusion of both wiring and removal makes it medium-sized but coherent — the
removal validates the wiring.

**Note:** Lock/caller_session_id removal overlaps with the scaffolded `next-machine-old-code-cleanup`
todo (not on roadmap). If phase 2 delivers these items, the cleanup todo should be closed/absorbed.

### 3. Verification — PASS

Verification is concrete: demo scripts assert function removal, schema registration, parameter
removal via AST inspection. `make test` and `make lint` provide integration-level verification.
The existing `test_integrator_wiring.py` covers cartridge behavior and will be updated to verify
the new three-event trigger logic.

### 4. Approach Known — PASS

The approach follows established patterns:
- `emit_branch_pushed()` mirrors `emit_review_approved()` and `emit_deployment_started()`
- Cartridge constructor injection matches the existing `spawn_callback` pattern
- Event type mapping is a simple dict lookup
- Lock/parameter removal is mechanical deletion with clear file locations

### 5. Research Complete — PASS

All components have been researched and traced:
- ReadinessProjection API: `apply()`, `_recompute()`, status transitions, READY criteria
- IntegrationTriggerCartridge: `process()` flow, `INTEGRATION_EVENT_TYPES`, `spawn_callback`
- IntegrationEventService: `ingest()` → `build_integration_event()` → `projection.apply()`
- Lock lifecycle: acquire (~L2165), release (~L2221), get_holder (~L2242), session death cleanup
- `caller_session_id`: traced through `next_work()` signature, API route, all conditional uses
- `emit_branch_pushed()`: confirmed missing from `integration_bridge.py`
- `BranchPushedPayload`: defined in `teleclaude/core/integration/events.py`
- `branch.pushed` event schema: NOT yet registered in catalog — needs creation

### 6. Dependencies & Preconditions — NEEDS_DECISION

**Blocker:** Roadmap declares `after: [event-system-cartridges]` but this appears to be a
false dependency.

`event-system-cartridges` delivers trust, enrichment, correlation, and classification
cartridges — system intelligence that processes ALL events flowing through the pipeline.
Phase 2 modifies the `IntegrationTriggerCartridge` which already exists and operates
independently in the pipeline. The cartridge's internal logic change (adding projection
consultation) does not depend on the system intelligence cartridges.

The pipeline ordering change from `event-system-cartridges` (adding trust/enrichment/
correlation/classification) is orthogonal to the integration trigger's behavior change.
The trigger cartridge will work correctly regardless of what other cartridges exist in the
pipeline before or after it.

**Decision needed:** Should the `event-system-cartridges` dependency be removed from the
roadmap for this slug?

### 7. Integration Safety — PASS

The change is incremental:
- New event schema and emit function are additive (no existing behavior changes)
- Cartridge modification replaces trigger logic (single-event → projection-based)
- Lock removal is safe because queue + projection provide serialization
- Landing as atomic commit prevents mid-transition breakage
- `ingest_callback=None` default preserves backward compat for existing tests during transition

### 8. Tooling Impact — N/A (auto-satisfied)

No tooling or scaffolding changes.

## Summary

| Gate | Status |
|------|--------|
| Intent & Success | PASS |
| Scope & Size | PASS |
| Verification | PASS |
| Approach Known | PASS |
| Research Complete | PASS |
| Dependencies | NEEDS_DECISION |
| Integration Safety | PASS |
| Tooling Impact | N/A |

**Draft score: 7** — all gates pass except the dependency question.

## Blockers

1. **Roadmap dependency on `event-system-cartridges`**: appears to be a false dependency.
   Needs human decision on whether to remove it before build can proceed.

## Assumptions (inferred)

1. The `teleclaude_events/` → `teleclaude.*` import boundary constraint applies here (confirmed
   in `event-system-cartridges` requirements: "Zero imports from `teleclaude.*` in
   `teleclaude_events/`").
2. The `BranchPushedPayload` type in `teleclaude/core/integration/events.py` is the canonical
   payload shape for `branch_pushed` events.
3. The finalize worker has access to `branch` and `sha` in its context for calling
   `emit_branch_pushed()`.

## Recommendations

1. Remove the `event-system-cartridges` dependency from this slug in the roadmap — the work
   is independent.
2. Close or absorb the `next-machine-old-code-cleanup` scaffolded todo after phase 2 delivers
   lock/caller_session_id removal.
3. Builder should verify that the `teleclaude_events/` → `teleclaude/*` import boundary is
   maintained by using constructor-injected callbacks.
