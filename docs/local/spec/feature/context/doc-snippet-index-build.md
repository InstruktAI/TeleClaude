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

```
Given a project with valid snippet sources under docs/
And the recorded commit is the project's latest canonical commit, or its checkout records a published generation and neither it nor an unfinished publication descends from the recorded commit
When commit-boundary publication runs for that recorded commit
Then the index-build phase runs
And the project's canonical checkout receives docs/local/index.yaml with one entry per valid committed local Source, identified as projects/<slug>/…, and paths rooted at that checkout
And its canonical checkout receives docs/third-party/index.yaml when committed third-party sources exist
And an agent's local telec docs retrieval reads those canonical-checkout indexes
```

#### UC-DIB7: Classification is derived from the source's path

```
Given a valid Source under docs/
When the index-build phase writes its entry
Then the entry carries id, type, scope, and domain derived from the Source's path
And a procedure Source's entry additionally carries its activation_trigger or its subscriptions, whichever it declares
```

#### UC-DIB8: A non-derivable path fails the build loudly

```
Given a Source whose path cannot derive id/type/scope (placement outside any known taxonomy root)
When the index-build phase runs
Then a hard build error is raised naming the path and the reason it is non-derivable
And the sync build fails
```

#### UC-DIB9: A source missing its authored description fails the build

```
Given a snippet file missing the authored description frontmatter
When validation runs ahead of the index build
Then a missing-description finding is reported for that file
And the sync exits with a non-zero status
```

#### UC-DIB10: H1 suffix correctness is left to validation

```
Given a Source whose H1 heading lacks the type suffix (e.g. "— Policy")
When validation runs ahead of the index build
Then a title-suffix finding is reported for that file
And the sync exits with a non-zero status
```

#### UC-DIB11: An unchanged catalog is not rewritten

```
Given a built index whose rendered YAML equals the on-disk file
When the index-build phase writes the result
Then the file is NOT rewritten (idempotent write)
And the mtime is preserved
```

#### UC-DIB12: A snippet without lifecycle metadata carries none

```
Given a snippet with no lifecycle metadata
When the lifecycle-metadata copy step runs
Then delivered_by is omitted from the index entry
```

#### UC-DIB13: A pending snippet's delivering slug reaches its entry

```
Given a snippet with delivered_by: [slug-a]
When the lifecycle-metadata copy step runs
Then delivered_by is copied into the index entry verbatim
```

#### UC-DIB2: Index build keeps authored Source bytes unchanged

```
Given a Source whose H1 heading lacks the expected type suffix
And its frontmatter scalars are double-quoted
When the index-build phase builds the payload
Then the Source file content is unchanged byte-for-byte
When the full index build writes index.yaml
Then the Source file content is still unchanged byte-for-byte
And the index.yaml file is produced
```

#### UC-DIB1: Parent entries derive superseded_by from pending carriers

```
Given a live parent snippet with a pending companion, a planned block, or a planned-change block
When the index-build phase writes the parent entry
Then the entry carries superseded_by with each owning slug
And the pending companion has no independent index entry
When telec docs index renders the parent line
Then the line includes " (superseded by: <slugs>)"
```

#### UC-DIB3: A doc-capable person tier gets both catalogs built

```
Given a person tier whose declaration says it carries documentation
And Sources authored in that tier's docs/global and docs/local
When the index build runs over the configuration surface
Then that tier's published catalog and local catalog are written
And the local catalog stays in the person's home
And an agent session permitted to read that tier finds each Source under people/<slug>/…, whichever half holds it
```

#### UC-DIB4: A doc-capable company tier gets both catalogs built

```
Given a company tier whose declaration says it carries documentation
And Sources authored in that tier's docs/global and docs/local
When the index build runs over the configuration surface
Then that company's published catalog and local catalog are written
And the local catalog stays in the company's home
And an agent session permitted to read that tier finds each Source under companies/<slug>/…, whichever half holds it
```

#### UC-DIB5: Catalog building follows the tier's own declaration

```
Given the platform home contains a declared person or company tier
And an undeclared sibling folder has the same documentation layout
When committed-source index construction enumerates tier catalogs
Then the declared tier receives a catalog
And the undeclared sibling receives none
And tier identity is never inferred from location on disk
```

#### UC-DIB14: A participating tier with no snippets keeps an empty catalog

```
Given a tier whose declaration records participation in the documentation surface
And that tier's documentation home holds no snippets
When the index build writes that tier's catalog
Then an index with no entries is written for each half of the tier's documentation home
And the catalog is not deleted for being empty
And its existence answers participation while its entries answer content
```

#### UC-DIB15: Tier snippet sources are validated like every other publisher's

```
Given a company or person tier whose declaration records participation in the documentation surface
And a snippet source under that tier's documentation home
And an undeclared sibling folder in the same layout also holds a snippet source
When source validation runs, scoped to that file or over the whole tree
Then the tier's documentation home is among the roots validation walks
And the source is validated under the same structural and classification rules as a project's or the global tree's
And the source beneath the undeclared sibling is not walked
```

#### UC-DIB16: An older publication replay preserves the checkout catalog

```gherkin
Given an agent can retrieve documentation introduced by a project's latest canonical commit
And an older failed publication range exists for that project
When maintenance replays the older range
Then the agent's local documentation retrieval still includes the newer committed documentation
And the checkout's catalog remains aligned with its latest canonical commit
```

#### UC-DIB17: One relative path in both halves of a tier home is refused

```gherkin
Given a person or company home holding a Source at the same relative path under docs/global and docs/local
When source validation runs ahead of the index build
Then a finding names both files as one identity
And the index build does not write either catalog from that source state
```

#### UC-DIB18: A project without a declared slug mints no identities

```gherkin
Given a project whose declaration yields no project slug
When the index build runs for that project
Then the build fails naming the project and the missing slug
And no identity is derived from the project's directory name
```

### Cross-context references

- **config** — supplies the project slug (from `teleclaude.yml`
  `project_slug` then `project_name`) and each person's and company's declared
  slug; the slug is the second segment of every identity the home owns
  (`projects/<slug>/…`, `people/<slug>/…`, `companies/<slug>/…`). A directory
  name never supplies it.

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
