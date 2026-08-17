---
description: 'Sync derives snippet metadata from paths, writes per-scope index.yaml catalogs, and preserves authored sources.'
visibility: 'public'
---

# Doc Snippet Index Build — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

The Index is the authoritative pre-computed catalog of every Source snippet in
a scope.


Sync walks the working tree, derives `id`/`type`/`scope`/`domain` from
each Source's path, renders portable paths, and writes per-scope `index.yaml`
files — one for the project, one for global baseline, one for third-party.


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
When validation runs ahead of the index build
Then a title-suffix finding is reported for that file
And the sync exits with a non-zero status
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

### Cross-context references

- **config** — supplies the project slug (from `teleclaude.yml`
  `project_slug` then `project_name`, falling back to the directory name);
  the resulting slug prefixes every snippet ID this project owns.

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
