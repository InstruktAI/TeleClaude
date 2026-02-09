---
id: 'project/spec/runtime-operations-truth'
type: 'spec'
scope: 'project'
description: 'Operational source of truth for TeleClaude daemon runtime operations, impact, and recovery steps.'
---

# Runtime Operations Truth — Spec

## What it is

A project-specific operational truth table for TeleClaude runtime operations.

It tells operators exactly:

- what background operations are running,
- how often they run,
- what breaks when they fail,
- and what to check first.

## Canonical fields

Each operation entry must include:

- operation name,
- run frequency,
- purpose,
- user-visible failure symptom,
- self-recovery behavior,
- first checks,
- safe recovery action.

## Allowed values

Recovery behavior:

- `yes`
- `partial`
- `no`

Checks and recovery actions must use approved project operational commands.

## Known caveats

- Frequencies can drift when runtime defaults change in code.
- This spec must stay in sync with actual daemon operations.
- Keep this practical for a small, low-traffic system; avoid heavy ops complexity.
