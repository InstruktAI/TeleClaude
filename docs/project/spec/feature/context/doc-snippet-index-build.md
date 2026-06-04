---
id: 'project/spec/feature/context/doc-snippet-index-build'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Sync builds the per-scope snippet index.yaml catalog from frontmatter, normalizes titles, and rejects cross-project ID collisions.'
---

# Doc Snippet Index Build — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

The Index is the authoritative pre-computed catalog of every Source snippet in
a scope. Sync walks the working tree, extracts frontmatter from each Source,
normalizes its presentation (titles, paths), and writes per-scope
`index.yaml` files — one for the project, one for global baseline, one for
third-party. Consumers (the Selection policy, the CLI verbs, peer agents)
read the Index instead of re-walking the tree, so discovery is fast and
deterministic. Cross-project ID collisions are detected at build time so two
projects cannot silently claim the same snippet identity.

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
Given a snippet file with malformed frontmatter (missing id or description)
When the index-build phase runs
Then the snippet is silently skipped and excluded from the Index
And no error is raised for that single snippet
```

```
Given a Source whose H1 heading lacks the type suffix (e.g. "— Policy")
When the index entry is rendered
Then the title-normalization step appends the type suffix derived from frontmatter type
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
Then status and delivered_by are omitted from the index entry
```

```
Given a snippet with status: target and delivered_by: [slug-a]
When the lifecycle-metadata copy step runs
Then both fields are copied into the index entry verbatim
```

### Cross-context references

- **config** — supplies the project slug (from `teleclaude.yml`
  `project_slug` then `project_name`, falling back to the directory name);
  the resulting slug prefixes every snippet ID this project owns.

## Known caveats

- Malformed frontmatter is silent. A snippet missing `id`, `description`,
  `type`, or `scope` is skipped without error, so it disappears from the Index
  with no diagnostic. Operators discover the gap only when downstream lookups
  fail to find the ID.
- Baseline title normalization only fires for folder names listed in the
  known type-suffix set. Snippets in unrecognized baseline folders get no
  title rewrite, producing inconsistent presentation.
- Project-slug path rewriting is a literal string substitution: `docs/global/`
  becomes `docs/` in the rendered index so the entry is portable to
  `~/.teleclaude/docs/`. Paths in the Index are NOT the working-tree paths;
  resolving back to a real file requires the reader to know which root applies.
- Third-party index generation runs a parallel `.md` flow alongside the
  `.yaml` flow that is likely vestigial. Shedding candidate for v2.
