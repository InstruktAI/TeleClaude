---
id: software-development/procedure/lifecycle/documentation/sync-snippets
type: procedure
scope: domain
description: Regenerate docs/snippets from code + docs using the taxonomy.
---

# Sync Snippets

## Objective

Regenerate `docs/snippets/` from code and existing documentation using the taxonomy lens.

## Rules

- **Stateless**: always run end-to-end, no conditional prechecks.
- **Snippets are output only**: never treat `docs/snippets/` as input.
- **Taxonomy**: every snippet uses exactly one taxonomy type and one scope.
- **Docstring trust**: treat docstrings as the primary summary of behavior; fall back to code/tests if a docstring is missing or unclear.

## Process

1. Read `README.md`, `AGENTS.md`, and `docs/**/*.md` excluding `docs/snippets/` and `docs/3rd-party/`.
2. Scan code entrypoints, adapters, state flows, and tests.
3. Create/refresh snippets across the taxonomy.
4. Rebuild `docs/snippets/index.yaml` and validate integrity.

## Output

- Updated `docs/snippets/` and `docs/snippets/index.yaml`.
