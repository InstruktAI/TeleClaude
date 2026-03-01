# DOR Report: mesh-trust-model

## Assessment Phase: Draft

### Summary

Draft artifacts created from the rich `input.md` brain dump. Requirements derived
covering the trust evaluator cartridge, trust ring storage, sovereignty config,
observation events, and management API. Implementation plan follows the existing
cartridge pattern with 5 phases.

### Artifact Status

| Artifact              | State                      |
| --------------------- | -------------------------- |
| `input.md`            | Complete — rich brain dump  |
| `requirements.md`     | Draft — derived from input  |
| `implementation-plan.md` | Draft — 5 phases, 12 tasks |
| `demo.md`             | Draft — 5 validation + 5 guided steps |
| `quality-checklist.md`| Scaffold — standard template |

### DOR Gate Analysis (Draft)

1. **Intent & success**: Clear. Per-event trust evaluation with immune system model.
   Success criteria are concrete and testable.
2. **Scope & size**: Moderate — 4 new files in `teleclaude_events/trust/`, 1 schema
   file, 1 API module, config additions, pipeline wiring. Fits a single session
   with careful execution.
3. **Verification**: Tests specified for all paths. Demo validation scripts defined.
4. **Approach known**: Follows existing cartridge pattern (dedup, notification).
   SQLite storage follows EventDB pattern. API follows existing daemon routes.
5. **Research complete**: No third-party dependencies needed. All patterns exist
   in the codebase.
6. **Dependencies**: Depends on `event-envelope-schema` and `mesh-architecture`.
   Both are `after:` dependencies in the roadmap. The trust evaluator is designed
   with a `SignatureVerifier` protocol stub so it can be built before
   `mesh-architecture` provides real crypto. The envelope model is used as-is.
7. **Integration safety**: The cartridge is inserted into the pipeline chain. Local
   events bypass entirely. New code in its own module. Risk of regression is low
   — existing pipeline tests verify chain integrity.
8. **Tooling impact**: No tooling changes.

### Open Questions

- **Database path**: Should `TrustDB` reuse the existing `EventDB` connection or
  create its own connection to the same SQLite file? The single-database policy
  says same file; implementation should share the connection to avoid WAL contention.
- **Dependency gating**: Should the builder block until `event-envelope-schema` is
  delivered, or can this be built in parallel with a clear integration contract?
  The `SignatureVerifier` stub pattern suggests parallel is viable.

### Assumptions

- The existing `EventEnvelope` model is sufficient for trust evaluation — no new
  envelope fields are required.
- The `trust:` config section will be added to the existing TeleClaude YAML config
  schema (config wizard exposure confirmed by convention).
- The daemon's SQLite database supports adding new tables without migration tooling
  (consistent with how `EventDB` creates tables at startup).

### Blockers

None identified. Dependencies are manageable with the stub pattern.
