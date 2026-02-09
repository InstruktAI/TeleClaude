---
id: 'software-development/policy/backward-compatibility-hygiene'
type: 'policy'
domain: 'software-development'
scope: 'global'
description: 'Backward compatibility hygiene rules for shipping stable releases without breaking consumers.'
---

# Backward Compatibility Hygiene — Policy

## Rules

- Treat compatibility as a default requirement, not an optional improvement.
- Do not introduce breaking changes in any non-major release.
- For pre-1.0 versions, this project still treats minor releases as non-breaking.
- For 1.0+ versions, breaking changes are allowed only in major releases.
- If a breaking change is unavoidable, document it explicitly before merge: what breaks, who is affected, migration path, and rollback plan.
- Compatibility decisions must be visible in PR notes or release notes, not implicit.
- When changing payload contracts (API/events/hooks), update tests and contract docs in the same change.

## Rationale

- Stability is a product feature.
- Small teams move faster when existing flows keep working by default.
- Explicit break procedures prevent accidental regressions disguised as refactors.

## Scope

- Applies to API contracts, WebSocket events, hook payloads, tool interfaces, and persisted state schemas.
- Applies to all repositories and adapters that consume TeleClaude contracts.

## Enforcement

- Reject PRs that change contracts without compatibility analysis.
- Require migration notes for any intentional break.
- Require tests for both unchanged and changed paths when contract behavior is touched.

## Exceptions

- Emergency security fixes may break behavior only when no safe compatible alternative exists.
- Exception requires explicit note in release communication with immediate migration guidance.
