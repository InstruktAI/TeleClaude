---
id: 'general/principle/intent-first-documentation'
type: 'principle'
scope: 'global'
description: 'Preserve intent, boundaries, and durable reasoning in documentation.'
---

# Intent First Documentation — Principle

## Principle

Documentation captures intent, boundaries, and durable reasoning that code cannot express.

## Rationale

- Code shows behavior, not why it exists.
- Intent prevents drift as implementations evolve.
- Boundaries keep decisions aligned across components and time.

## Implications

- Prioritize invariants, constraints, and decision context.
- Keep documentation focused on what must remain true after refactors.

## Tensions

- Detailed implementation notes can distract from intent.
- Over-documenting can slow iteration if not focused on durable knowledge.
