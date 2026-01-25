---
description:
  Assess input.md readiness using Definition of Ready criteria and decide
  whether to split.
id: software-development/procedure/lifecycle/prepare/input-assessment
scope: domain
type: procedure
---

# Input Assessment — Procedure

## Goal

- @docs/software-development/policy/definition-of-ready

If `todos/{slug}/input.md` exists and `todos/{slug}/state.json` lacks `breakdown.assessed`, perform readiness assessment.

1. **Single-session completability**
2. **Verifiability** (tests or concrete checks)
3. **Atomicity** (clean boundaries)
4. **Scope clarity** (unambiguous requirements)
5. **Uncertainty level** (approach known or needs exploration)

If any criterion fails, apply story-splitting patterns.

### If Breakdown Is Needed

1. Create focused todos: `todos/{slug}-1/`, `todos/{slug}-2/`, etc.
2. Each new `input.md` is a clean briefing (intended outcome only).
3. Update `todos/dependencies.json`: add `"{slug}": ["{slug}-1", "{slug}-2"]`.
4. Update `todos/roadmap.md`: insert new slugs before `{slug}`.
5. Create `todos/{slug}/breakdown.md` with split reasoning.
6. Update `todos/{slug}/state.json`:
   ```json
   { "breakdown": { "assessed": true, "todos": ["{slug}-1", "{slug}-2"] } }
   ```

### If No Breakdown Is Needed

Update `todos/{slug}/state.json`:

```json
{ "breakdown": { "assessed": true, "todos": [] } }
```

- TBD.

- TBD.

- TBD.

- TBD.

## Preconditions

- TBD.

## Steps

- TBD.

## Outputs

- TBD.

## Recovery

- TBD.
