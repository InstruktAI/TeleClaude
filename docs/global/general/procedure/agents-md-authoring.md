---
id: general/procedure/agents-md-authoring
type: procedure
scope: global
description: Author AGENTS.md files that bootstrap required reads and role context.
---

# Agents Authoring — Procedure

## Goal

Author AGENTS.md files that correctly bootstrap required reads and role context.

## Preconditions

- Baseline and general indexes exist.
- Required reads references are known.

## Steps

1. Create or update AGENTS.md at the repository root.
2. Add required reads as inline `@` references.
3. Keep content minimal and role-specific.
4. Ensure references resolve to existing snippets.
5. Validate with snippet tooling.

## Outputs

- Updated AGENTS.md with correct required reads.

## Recovery

- Fix broken references and re-run validation.
