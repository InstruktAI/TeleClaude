---
description: 'Sync derives snippet metadata from paths, writes per-scope index.yaml catalogs, and preserves authored sources.'
visibility: 'public'
---

# Doc Snippet Index Build — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

The Index is the authoritative pre-computed catalog of every Source snippet in
a scope.

Index construction derives `id`/`type`/`scope`/`domain` from
each Source's path and its home's declaration, renders portable paths, and
writes one `index.yaml` per catalog: one per documentation half of each home —
a project's published and local halves, and both halves of every person and
company tier whose declaration says its material participates in
documentation — plus third-party. Local catalogs store qualified identities.
Construction covers every participating tier rather than a fixed list.

The
index build reads authored Source snippets but never rewrites them; source
correctness is enforced by validation before commit. The derived metadata makes
`index.yaml` the single source of truth: Sources no longer author
`id`/`type`/`scope`/`domain` in frontmatter. Consumers (the Selection policy,
the CLI verbs, peer agents) read the Index instead of re-walking the tree, so
discovery is fast and deterministic. Global-docs integrity is one owner per
domain, enforced at deploy time by split-domain detection (see the agent
runtime deployment spec); the index build itself derives and writes metadata and
does not police cross-project ownership.

## Canonical fields

### Use cases

#### UC-DIB6: A project's catalog is written from its sources

#### UC-DIB7: Classification is derived from the source's path

#### UC-DIB8: A non-derivable path fails the build loudly

#### UC-DIB9: A source missing its authored description fails the build

#### UC-DIB10: H1 suffix correctness is left to validation

#### UC-DIB11: An unchanged catalog is not rewritten

#### UC-DIB12: A snippet without lifecycle metadata carries none

#### UC-DIB13: A pending snippet's delivering slug reaches its entry

#### UC-DIB2: Index build keeps authored Source bytes unchanged

#### UC-DIB1: Parent entries derive superseded_by from pending carriers

#### UC-DIB3: A doc-capable person tier gets both catalogs built

#### UC-DIB4: A doc-capable company tier gets both catalogs built

#### UC-DIB5: Catalog building follows the tier's own declaration

#### UC-DIB14: A participating tier with no snippets keeps an empty catalog

#### UC-DIB15: Tier snippet sources are validated like every other publisher's

#### UC-DIB16: An older publication replay preserves the checkout catalog

#### UC-DIB17: One relative path in both halves of a tier home yields two snippets

#### UC-DIB18: A project without a declared slug mints no identities

#### UC-DIB19: A tier source that authors its own classification is refused before the index build

### Cross-context references

- **config** — supplies the project slug (from `teleclaude.yml`
  `project_slug` then `project_name`) and each person's and company's declared
  slug; the slug is the segment after the home prefix in every identity the
  home owns (`people/<slug>/…`, `companies/<slug>/…`, and the local forms
  `local/projects/<slug>/…`, `local/people/<slug>/…`, `local/companies/<slug>/…`).
  A directory name never supplies it.

## Known caveats

- Non-derivable paths fail loudly. A Source whose path cannot yield
  `id`/`type`/`scope` raises a hard build error naming the path and reason, so
  the sync build stops rather than silently dropping the snippet from the Index.
- Source H1 suffix correctness is enforced by snippet validation, not by the
  index build. The index build assumes source has already passed the validation
  gate and does not rewrite headings.
- Project-slug path rewriting is a literal string substitution: `docs/global/`
  becomes `docs/` in the rendered index so the entry is portable to
  `~/.teleclaude/docs/`. Paths in the Index are NOT the working-tree paths;
  resolving back to a real file requires the reader to know which root applies.
- Third-party index generation runs a parallel `.md` flow alongside the
  `.yaml` flow that is likely vestigial. Shedding candidate for v2.
