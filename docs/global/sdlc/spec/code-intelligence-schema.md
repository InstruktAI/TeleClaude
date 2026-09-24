---
description: 'Canonical schema contract for code intelligence: structural entities, relationships, provenance, confidence, and role-specific result views.'
visibility: 'public'
---

# Code Intelligence Schema — Spec

## What it is

Defines the minimum canonical contract for code-intelligence facts and result
views so multiple SDLC consumers can reason from the same structural substrate.

## Canonical fields

### Canonical entities

- `file`
- `symbol`
- `contract`
- `test`
- `snippet`

### Canonical relationships

- `contains`
- `imports`
- `calls`
- `defines`
- `consumes`
- `tested_by`
- `documented_by`

### Required metadata on entities/results

- stable identifier
- source location / provenance
- freshness relative to the active work surface
- confidence / blind-spot status where applicable
- boundary status
- derived metrics relevant to the entity or consumer

### Documentation metadata

Where code-intelligence extracts inline code descriptions or linked
documentation, the schema must support:

- node-level description presence/status
- description provenance/source
- documentation linkage through `documented_by`
- drift or freshness signals between code and linked documentation

### Result-view contract

All consumer views are structured projections over the canonical facts. Result
views must preserve:

- provenance
- freshness/degradation signals
- confidence / blind-spot markers
- enough structural identifiers that downstream consumers can verify or enrich
  the result without re-deriving the world

## Allowed values

- coverage status:
  - `complete`
  - `partial`
  - `unsupported`
- confidence status:
  - `high`
  - `partial`
  - `suppressed`
- consumer view families:
  - `planner`
  - `reviewer`
  - `refactor_planner`

## Known caveats

- The schema must stay language-agnostic even when only one extractor is
  implemented initially.
- Role-specific views may add projection-specific fields, but they must not
  violate or reinterpret canonical facts.
- Blind spots are part of the contract, not an error-reporting afterthought.
