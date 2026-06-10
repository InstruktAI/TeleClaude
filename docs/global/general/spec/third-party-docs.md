---
description: 'Conventions for third-party documentation storage and references.'
visibility: 'public'
---

# Third-Party Docs — Spec

## What it is

Defines the project and global convention for third-party documentation storage and how it is referenced.

## Canonical fields

- Third-party global docs live under `~/.teleclaude/docs/third-party/`.
- Third-party project docs live under `docs/third-party/`.
- Third-party docs are indexed separately from taxonomy snippets.
- Third-party frontmatter uses `id`, `type`, `scope`, and `description`.
- Third-party `id` is derived from the path below the third-party root, prefixed with `third-party/`.
- Third-party `type` is always `third-party`.
- Third-party `scope` is `project` for project docs and `global` for global docs.
- Third-party sources are **never** required reads and must not use inline `@` references.
- Cite third-party sources only under `Sources` or `See also` when authoritative references are available.

## Allowed values

- `docs/third-party/<vendor-or-topic>/...` for curated third-party summaries.
- `id`: `third-party/<vendor-or-topic>/<slug>`.
- `type`: `third-party`.
- `scope`: `project` or `global`.

## Known caveats

- Third-party docs do not use the taxonomy `type` values.
- Third-party docs do not require `Required reads`.
- `Sources` entries, when present, must be authoritative web links or Context7 snippet IDs.
