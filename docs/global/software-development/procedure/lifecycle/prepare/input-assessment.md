---
description: Assess input.md readiness using Definition of Ready criteria and decide
  whether to split.
id: software-development/procedure/lifecycle/prepare/input-assessment
scope: domain
type: procedure
---

# Input Assessment — Procedure

## Goal

- @~/.teleclaude/docs/software-development/policy/definition-of-ready.md

If `todos/{slug}/input.md` exists and `todos/{slug}/state.json` lacks `breakdown.assessed`, perform readiness assessment.

1. **Single-session completability**
2. **Verifiability** (tests or concrete checks)
3. **Atomicity** (clean boundaries)
4. **Scope clarity** (unambiguous requirements)
5. **Uncertainty level** (approach known or needs exploration)

If any criterion fails, apply story-splitting patterns.

## Preconditions

- `todos/{slug}/input.md` exists.
- `todos/{slug}/state.json` exists.

## Steps

1. Assess readiness against the five criteria (single-session, verifiable, atomic, clear scope, known approach).
2. If breakdown is needed:
   - Create focused todos: `todos/{slug}-1/`, `todos/{slug}-2/`, etc.
   - Each new `input.md` is a clean briefing (intended outcome only).
   - Update `todos/dependencies.json` with the new slugs.
   - Update `todos/roadmap.md` to insert new slugs before `{slug}`.
   - Create `todos/{slug}/breakdown.md` with split reasoning.
   - Update `todos/{slug}/state.json`:
     ```json
     { "breakdown": { "assessed": true, "todos": ["{slug}-1", "{slug}-2"] } }
     ```
3. If no breakdown is needed, update `todos/{slug}/state.json`:
   ```json
   { "breakdown": { "assessed": true, "todos": [] } }
   ```

## Outputs

- `state.json` updated with breakdown assessment.
- New todos created if needed.

## Recovery

- If input is insufficient, request clarification and pause preparation.
