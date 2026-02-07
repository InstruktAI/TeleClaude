---
id: 'project/policy/feature-flag-usage'
type: 'policy'
scope: 'project'
description: 'Rules for when to use feature flags and when to avoid them.'
---

# Feature Flag Usage — Policy

## Rules

- Use feature flags only when the benefit justifies the added complexity.
- Use feature flags for agent-specific behavior (e.g., testing on Gemini before Claude).
- Use feature flags for runtime toggles that need on/off control without restarts.
- Use feature flags for behavioral experiments comparing approaches with metrics.
- Do not use feature flags for simple replacements where git revert suffices as rollback.
- Do not use feature flags for one-time migrations that will delete the old code path.
- Do not use feature flags to enable "gradual rollout" in single-user systems.

## Rationale

- Feature flags create dual code paths that require maintenance.
- Unnecessary flags add complexity without benefit.
- Git history provides rollback for simple replacements; flags are redundant.

## Scope

- Applies to all feature flag decisions in TeleClaude.

## Enforcement

- Review feature flag proposals against these rules before implementation.
- If the rollback plan is "disable flag and use old code," prefer git revert instead.

## Exceptions

- None.
