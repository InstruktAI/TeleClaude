---
description: Regenerate docs from code and existing documentation using the taxonomy.
id: software-development/procedure/lifecycle/documentation/sync-docs
scope: domain
type: procedure
---

# Sync Docs — Procedure

## Goal

Regenerate `docs/` from code and existing documentation using the taxonomy lens.

## Preconditions

- Repository is clean enough to regenerate docs.
- `docs/` and `docs-3rd/` are available.

## Steps

1. Read `README.md`, `AGENTS.md`, and `docs/**/*.md` excluding `docs/` and `docs-3rd/`.
2. Scan code entrypoints, adapters, state flows, and tests.
3. Create or refresh docs across the taxonomy.
4. Rebuild `docs/index.yaml` and validate integrity.

## Report format

```
DOCS SYNC COMPLETE

Snippets updated: {count}
Index rebuilt: yes
Validation: PASSING
```

## Outputs

- Updated `docs/` and `docs/index.yaml`.

## Recovery

- If validation fails, report the errors and stop.
