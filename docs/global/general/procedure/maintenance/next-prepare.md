---
id: 'general/procedure/maintenance/next-prepare'
type: 'procedure'
scope: 'global'
description: 'Orchestration procedure for next-prepare. Routes work to draft or gate procedures with strict phase separation.'
---

# Next Prepare Maintenance — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/maintenance/next-prepare-draft.md
@~/.teleclaude/docs/general/procedure/maintenance/next-prepare-gate.md

## Goal

Route todo preparation through two separate phases:

1. Draft phase for artifact creation/refinement.
2. Gate phase for formal DOR validation.

Draft and gate must run in separate worker sessions.

## Preconditions

1. `todos/roadmap.md` exists.
2. Target slug is active (not icebox, not delivered) when slug is provided.
3. Worker command selected is explicit: `next-prepare-draft` or `next-prepare-gate`.

## Steps

1. Inspect slug state.
2. If requirements or implementation plan are missing, route to draft.
3. If both exist but DOR is not final pass, route to gate.
4. Enforce session isolation: Terminate any active draft session before dispatching the gate session. Never reuse the same worker session for both phases.
5. Only gate outcomes can authorize readiness transition criteria.

## Outputs

1. Clear phase routing decision.
2. Draft artifacts from draft phase.
3. Final DOR verdict from gate phase.

### DOR contract

Per processed slug, both phases may update:

- `requirements.md`
- `implementation-plan.md`
- `dor-report.md`
- `state.json` (`dor` section)

`state.json.dor` schema:

```json
{
  "dor": {
    "last_assessed_at": "2026-02-09T17:00:00Z",
    "score": 8,
    "status": "pass",
    "schema_version": 1,
    "blockers": [],
    "actions_taken": {
      "requirements_updated": true,
      "implementation_plan_updated": true
    }
  }
}
```

Allowed values:

- `dor.score`: integer `1..10`
- `dor.status`: `pass`, `needs_work`, `needs_decision`

Threshold constants:

- Target quality: `8`
- Decision required: `< 7`

Phase transition: when `requirements.md` and `implementation-plan.md` exist, item phase is `pending`, and `dor.status == "pass"`, transition phase to `ready`. Only `next-prepare-gate` may authorize this.

## Recovery

1. If phase routing is ambiguous, default to draft and record ambiguity in `dor-report.md`.
2. If gate lacks required draft artifacts, stop and return `needs_work` with missing files listed.
