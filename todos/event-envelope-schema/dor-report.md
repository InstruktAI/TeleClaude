# DOR Report: event-envelope-schema

## Draft Assessment

### Intent & Success (Gate 1)
**Status: Pass**

The problem statement is explicit: formalize the existing `EventEnvelope` model as the
canonical wire format with core taxonomy, expansion joint, versioning, and JSON Schema
export. Success criteria are concrete and testable (round-trip tests, catalog coverage,
schema export validation).

### Scope & Size (Gate 2)
**Status: Pass**

The work is additive and contained within `teleclaude_events/`. No cross-cutting changes
to the daemon core. Each phase is independent — expansion joint, taxonomy registration,
versioning constant, and schema export can be implemented and tested in isolation. Fits
a single AI session.

### Verification (Gate 3)
**Status: Pass**

Clear verification path: unit tests for round-trip integrity, catalog coverage assertions,
JSON Schema validation against real envelopes. Demo script validates end-to-end. `make test`
and `make lint` as final gates.

### Approach Known (Gate 4)
**Status: Pass**

The technical path uses established patterns:
- Pydantic `ConfigDict(extra="allow")` for expansion joint
- Existing `schemas/` module pattern for taxonomy registration
- Module-level constant for versioning
- `model_json_schema()` for JSON Schema export
- Redis stream `_extra` key for flat-dict serialization of extra fields

No unknowns. All patterns have precedent in the codebase or Pydantic documentation.

### Research Complete (Gate 5)
**Status: Pass (auto-satisfied)**

No new third-party dependencies. All implementation uses Pydantic built-ins and existing
Redis stream patterns.

### Dependencies & Preconditions (Gate 6)
**Status: Pass**

No prerequisite tasks. The `teleclaude_events` package exists and is functional. Redis
stream infrastructure is in place. No new configuration needed.

### Integration Safety (Gate 7)
**Status: Pass**

All changes are additive:
- `extra="allow"` is backward-compatible (existing envelopes without extra fields work identically)
- New catalog entries don't affect existing event processing
- `SCHEMA_VERSION` constant replaces a hardcoded `1` — no behavioral change
- JSON Schema export is a new utility, not a modification

Rollback: revert the commit. No data migration needed.

### Tooling Impact (Gate 8)
**Status: Pass (auto-satisfied)**

No tooling or scaffolding changes.

## Assumptions

1. The `_extra` key strategy for Redis stream serialization is sufficient. Extra fields
   are JSON-encoded into a single key rather than polluting the flat dict namespace.
2. The flat naming pattern (`node.alive`, `deployment.started`) coexists with the
   existing `domain.` prefix pattern. No renaming of existing events.
3. `SCHEMA_VERSION = 1` is correct for the current state. It will be bumped when the
   envelope structure itself changes (fields added/removed/renamed).

## Open Questions

None blocking. The assumptions above are reasonable defaults that can be revisited
if the gate assessment identifies issues.
