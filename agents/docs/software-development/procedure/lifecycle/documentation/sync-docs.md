---
id: software-development/procedure/lifecycle/documentation/sync-docs
type: procedure
scope: domain
description: Regenerate docs from code + docs using the taxonomy.
---

# Sync Docs

## Objective

Regenerate `docs/` from code and existing documentation using the taxonomy lens.

## Rules

- **Stateless**: always run end-to-end, no conditional prechecks.
- **Docs are output only**: never treat `docs/` as input.
- **Taxonomy**: every snippet uses exactly one taxonomy type and one scope.
- **Docstring trust**: treat docstrings as the primary summary of behavior; fall back to code/tests if a docstring is missing or unclear.

## Process

1. Read `README.md`, `AGENTS.md`, and `docs/**/*.md` excluding `docs/` and `docs-3rd/`.
2. Scan code entrypoints, adapters, state flows, and tests.
3. Create/refresh docs across the taxonomy.
4. Rebuild `docs/index.yaml` and validate integrity.

## Output

- Updated `docs/` and `docs/index.yaml`.
