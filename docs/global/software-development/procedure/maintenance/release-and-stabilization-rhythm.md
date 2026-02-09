---
id: 'software-development/procedure/maintenance/release-and-stabilization-rhythm'
type: 'procedure'
domain: 'software-development'
scope: 'domain'
description: 'Small-team release rhythm that prioritizes stability with lightweight checks and clear rollback triggers.'
---

# Release And Stabilization Rhythm — Procedure

## Goal

Ship useful changes while protecting day-to-day stability.

## Preconditions

- Current system health is known.
- Release scope is explicitly written.
- Rollback path is known before release starts.

## Steps

1. Classify release type:
   - patch fix,
   - maintenance release,
   - higher-risk change window.
2. Run pre-release checks:
   - service health,
   - no unresolved severe incident,
   - clear scope,
   - rollback readiness.
3. Execute release in small controlled batch.
4. Perform required restart/verification steps.
5. Run short stabilization watch period.
6. Trigger rollback/hotfix if stability degrades.

Practical release rules:

- Keep batches small and related.
- Avoid mixing risky refactors with urgent bug fixes.
- Prefer boring release steps over clever release steps.

## Outputs

- Stable release execution with clear verification evidence.
- Reduced regression frequency.
- Faster recovery when regressions occur.

## Recovery

If release introduces instability:

1. Stop adding new change.
2. Apply rollback or focused hotfix.
3. Re-verify health immediately.
4. Record incident and prevention action before next non-urgent release.
