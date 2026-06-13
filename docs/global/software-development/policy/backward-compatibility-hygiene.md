---
description: 'Backward compatibility hygiene rules for shipping stable releases without breaking consumers.'
visibility: 'public'
---

# Backward Compatibility Hygiene — Policy

## Rules

Two regimes travel under "compatibility." Which one applies is decided by **who consumes the shape**, not by where it is stored.

### External contracts — preserve, deprecate with a window

Shapes consumed by independent parties that cannot be rolled forward atomically: API payloads, WebSocket events, hook payloads, tool interfaces, and any contract crossing a multi-version fleet.

- Treat compatibility as a default requirement, not an optional improvement.
- Do not introduce breaking changes in any non-major release. Pre-1.0, minor releases are still non-breaking; for 1.0+, breaking changes are allowed only in major releases.
- Evolve a shared shape additively until the slowest consumer has caught up; readers tolerate unknown fields rather than reject them.
- Retire a contract through deprecation with an explicit window: mark the old surface, keep it serving for the window, and document before merge what breaks, who is affected, the migration path, and the rollback plan.
- Compatibility decisions are visible in PR or release notes, not implicit.
- When a payload contract changes, update its tests and contract docs in the same change.

### Owned internal data — migrate forward, never branch

Shapes with no independent consumer: persisted aggregate state, config documents, and artifact bodies — data the project wholly owns and can roll forward at will.

- Bring the stored shape forward to the current contract before any domain code consumes it. Domain code knows only the latest shape.
- Roll the data forward with the platform's migration mechanism — an eager migration step, or lazy migrate-on-read where the platform provides an upcaster — then delete the old-shape handling.
- A backward-compatibility branch for an old owned shape is a defect, not a pragmatic exception. Version tolerance is never smeared through domain logic.
- A test never pins a superseded owned shape. Tests assert the current contract; each `vN → vN+1` migration step carries its own golden-fixture test. A test asserting a retired shape makes the dead path load-bearing and is removed with it.
- Where a forward migration is genuinely not yet available and a tolerance branch is unavoidable, it is interim debt isolated behind the migration boundary, never a permanent fork.

## Rationale

- The two regimes have opposite correct answers, and conflating them is what produces version-branched domain code. An external contract has consumers you cannot move atomically, so a deprecation window is the safe path. Owned data has no such consumer, so the safe path is to move it forward and delete the old shape — a window would only legitimize a second code path you carry forever.
- Stability is a product feature; for external contracts, existing flows keep working by default.
- For owned data, forward migration is what makes the no-cruft rule enforceable: old-shape handling lives in one named, tested migration step instead of accreting through every read path.
- Explicit break procedures prevent accidental regressions disguised as refactors.

## Scope

- External regime: API contracts, WebSocket events, hook payloads, tool interfaces, and all repositories and adapters that consume those contracts.
- Owned regime: persisted aggregate state, config documents, artifact bodies, and any stored shape the project migrates rather than exposes.

## Enforcement

- Reject a change to an external contract that lacks compatibility analysis; require migration notes for any intentional break.
- Reject a backward-compatibility branch on owned data where a forward migration is the contract; reject a test that pins a superseded owned shape. The paradigm-fit and tests review lanes enforce this.
- Require tests for both unchanged and changed paths when an external contract's behavior is touched.

## Exceptions

- Emergency security fixes may break an external contract only when no safe compatible alternative exists, with an explicit note in release communication and immediate migration guidance.
