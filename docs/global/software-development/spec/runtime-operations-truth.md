---
id: 'software-development/spec/runtime-operations-truth'
type: 'spec'
domain: 'software-development'
scope: 'domain'
description: 'Canonical format and content requirements for documenting live runtime operations and their failure impact.'
---

# Runtime Operations Truth — Spec

## What it is

A canonical specification for documenting runtime operations (loops/workers/watchers) in plain operational terms.

It defines what information must exist so operators can diagnose instability quickly.

## Canonical fields

Each runtime operation entry must include:

- operation name,
- trigger type (timer/event/manual),
- run frequency,
- responsibility (what it does),
- critical data touched,
- user-visible failure symptom,
- self-recovery behavior,
- first operator checks,
- safe recovery action.

Recommended table columns:

- Operation
- Run frequency
- What it does
- User-visible failure symptom
- Self-recovery
- First checks

## Allowed values

Trigger type:

- `timer`
- `event`
- `manual`

Self-recovery status:

- `yes`
- `partial`
- `no`

Recovery actions must use approved operational controls for the project where applied.

## Known caveats

- Operation frequency can drift if runtime defaults change. Update this spec instance whenever runtime intervals change.
- "Healthy" behavior must be defined by practical symptoms, not by idealized architecture.
- Avoid enterprise observability overhead for low-traffic small-team systems; keep this focused on real failure diagnosis.
