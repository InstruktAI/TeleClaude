---
description: 'Conventions for third-party documentation storage and references.'
visibility: 'public'
---

# Third-Party Docs — Spec

## What it is

Defines the project and global convention for factual documentation about one
upstream party and how that documentation is referenced. An upstream party is
one independently versioned authority: a project, product, protocol, library,
framework, or tool with its own release lifecycle or governing source.

## Canonical fields

- Third-party global docs live under `~/.teleclaude/docs/third-party/`.
- Third-party project docs live under `docs/third-party/`.
- Third-party docs are indexed separately from taxonomy snippets.
- One root below the third-party directory documents exactly one upstream
  party. Related projects with separate authorities or release lifecycles use
  separate roots even when one is built on the other.
- Third-party frontmatter authors only `description`; `id` and `scope` are
  derived from the path, and third-party docs carry no authored `type`.
- Third-party `id` is derived from the path below the third-party root, prefixed with `third-party/`.
- Third-party `scope` is `project` for project docs and `global` for global docs.
- Third-party content records verified upstream behavior, configuration,
  constraints, maturity, sources, and explicit gaps. Cross-party comparisons,
  adoption decisions, and platform-specific architecture belong to the
  relevant research or design artifact, not to any party's documentation.
- Third-party sources are **never** required reads and must not use inline `@` references.
- Cite third-party sources only under `Sources` or `See also` when authoritative references are available.

## Allowed values

- `docs/third-party/<upstream-party>/...` for project-specific third-party
  summaries, in every project except the mother.
- `~/.teleclaude/docs/third-party/<upstream-party>/...` for reusable
  third-party summaries. They are authored and committed in the mother
  project's `docs/third-party/<upstream-party>/...` and reach the deployed
  root only through documentation publication, which replaces that root from
  the mother's committed source; nothing is written into the deployed root
  directly.
- `id`: `third-party/<upstream-party>/<slug>`.
- `scope`: `project` or `global`.

## Known caveats

- Third-party docs do not use the taxonomy `type` values.
- Third-party docs do not require `Required reads`.
- `Sources` entries, when present, must be authoritative web links or Context7 snippet IDs.
- A landscape or comparison spanning multiple upstream parties is not a
  third-party root. Store it in the local research or design authority and
  cite the separate party documents under `Sources` or `See also`.
