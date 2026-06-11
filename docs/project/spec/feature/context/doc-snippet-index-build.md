---
description: 'Sync derives snippet metadata from paths, writes per-scope index.yaml catalogs, normalizes titles, and rejects cross-project ID collisions.'
visibility: 'public'
---

# Doc Snippet Index Build — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

The Index is the authoritative pre-computed catalog of every Source snippet in
a scope. Sync walks the working tree, derives `id`/`type`/`scope`/`domain` from
each Source's path, normalizes its presentation (titles, paths), and writes
per-scope `index.yaml` files — one for the project, one for global baseline, one
for third-party. The derived metadata makes `index.yaml` the single source of
truth: Sources no longer author `id`/`type`/`scope`/`domain` in frontmatter.
Consumers (the Selection policy, the CLI verbs, peer agents) read the Index
instead of re-walking the tree, so discovery is fast and deterministic.
Cross-project ID collisions are detected at build time so two projects cannot
silently claim the same snippet identity.

## Canonical fields

### Use cases

```
Given a project with valid snippet sources under docs/
When the operator runs telec sync
Then the index-build phase runs
And docs/project/index.yaml is written with one entry per valid Source
And docs/third-party/index.yaml is written when third-party sources exist
```

```
Given a valid Source under docs/
When the index-build phase writes its entry
Then the entry carries id, type, scope, and domain derived from the Source's path
And a procedure Source's entry additionally carries its activation_trigger
```

```
Given a Source whose path cannot derive id/type/scope (placement outside any known taxonomy root)
When the index-build phase runs
Then a hard build error is raised naming the path and the reason it is non-derivable
And the sync build fails
```

```
Given a snippet file missing the authored description frontmatter
When validation runs ahead of the index build
Then a missing-description finding is reported for that file
And the sync exits with a non-zero status
```

```
Given a Source whose H1 heading lacks the type suffix (e.g. "— Policy")
When the index entry is rendered
Then the title-normalization step appends the type suffix derived from the path-derived type
And the rewrite is idempotent on subsequent builds
```

```
Given a snippet ID already owned by another project in ~/.teleclaude/docs/index.yaml
When the current project syncs that same ID
Then the cross-project collision check raises and the sync build fails
And the operator must rename or remove the conflicting Source
```

```
Given a built index whose rendered YAML equals the on-disk file
When the index-build phase writes the result
Then the file is NOT rewritten (idempotent write)
And the mtime is preserved
```

```
Given a snippet with no lifecycle metadata
When the lifecycle-metadata copy step runs
Then delivered_by is omitted from the index entry
```

```
Given a snippet with delivered_by: [slug-a]
When the lifecycle-metadata copy step runs
Then delivered_by is copied into the index entry verbatim
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


### Cross-context references

- **config** — supplies the project slug (from `teleclaude.yml`
  `project_slug` then `project_name`, falling back to the directory name);
  the resulting slug prefixes every snippet ID this project owns.

## Known caveats

- Non-derivable paths fail loudly. A Source whose path cannot yield
  `id`/`type`/`scope` raises a hard build error naming the path and reason, so
  the sync build stops rather than silently dropping the snippet from the Index.
- Baseline title normalization only fires for folder names listed in the
  known type-suffix set. Snippets in unrecognized baseline folders get no
  title rewrite, producing inconsistent presentation.
- Project-slug path rewriting is a literal string substitution: `docs/global/`
  becomes `docs/` in the rendered index so the entry is portable to
  `~/.teleclaude/docs/`. Paths in the Index are NOT the working-tree paths;
  resolving back to a real file requires the reader to know which root applies.
- Third-party index generation runs a parallel `.md` flow alongside the
  `.yaml` flow that is likely vestigial. Shedding candidate for v2.
