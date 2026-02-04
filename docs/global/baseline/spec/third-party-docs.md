# Third-Party Docs — Spec

## What it is

Defines the project and global convention for third-party documentation storage and how it is referenced.

## Canonical fields

- Third-party global docs live under `~/.teleclaude/docs/third-party/`.
- Third-party project docs live under `docs/third-party/`.
- Third-party sources are **never** required reads and must not use inline `@` references.
- Cite third-party sources only under `Sources` or `See also`.

## Allowed values

- `docs/third-party/<vendor-or-topic>/...` for curated third-party summaries.

## Known caveats

- Third-party doc snippets must include a `Sources` section with authoritative links or Context7 snippet IDs.
