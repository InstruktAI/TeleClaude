---
id: 'project/spec/feature/context/doc-snippet-index-build'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
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
Then sync phase 2 calls build_all_indexes()
And docs/project/index.yaml is written with one entry per valid Source
And docs/third-party/index.yaml is written when third-party sources exist
```

```
Given a snippet file with malformed frontmatter (missing id or description)
When build_index_payload runs
Then the snippet is silently skipped and excluded from the Index
And no error is raised for that single snippet
```

```
Given a Source whose H1 heading lacks the type suffix (e.g. "— Policy")
When the index entry is rendered
Then _normalize_title appends the type suffix derived from frontmatter type
And the rewrite is idempotent on subsequent builds
```

```
Given a snippet ID already owned by another project in ~/.teleclaude/docs/index.yaml
When the current project syncs that same ID
Then check_global_collisions raises and the sync build fails
And the operator must rename or remove the conflicting Source
```

```
Given a built index whose rendered YAML equals the on-disk file
When build_all_indexes writes the result
Then the file is NOT rewritten (idempotent write)
And the mtime is preserved
```

```
Given a snippet with status: actual
When _copy_status_metadata runs
Then status and delivered_by are omitted from the index entry
```

```
Given a snippet with status: target and delivered_by: [slug-a]
When _copy_status_metadata runs
Then both fields are copied into the index entry verbatim
```

### Implementation pointers (v1)

- `teleclaude/docs_index.py:502-623` — `build_index_payload()` orchestrator
- `teleclaude/docs_index.py:560-593` — frontmatter extraction loop
- `teleclaude/docs_index.py:146-155` — `_copy_status_metadata()` status/delivered_by filter
- `teleclaude/docs_index.py:163-180` — `_normalize_title()` H1 type-suffix rewrite
- `teleclaude/docs_index.py:195-231` — `remove_non_baseline_indexes` stale cleanup
- `teleclaude/docs_index.py:407-428` — `get_project_slug()` priority chain
- `teleclaude/docs_index.py:436-494` — `check_global_collisions()` cross-project guard
- `teleclaude/docs_index.py:524-557` — baseline path/type inference
- `teleclaude/docs_index.py:639-642` — idempotent write
- `teleclaude/docs_index.py:647-662` — `build_all_indexes()` entry point
- `teleclaude/sync.py:90-95` — invocation from sync

### Cross-context references

- **config** — `get_project_slug()` reads `teleclaude.yml` (`project_slug` then `project_name`) before falling back to the directory name; the resulting slug prefixes every snippet ID this project owns.

## Known caveats

- Malformed frontmatter is silent. A snippet missing `id`, `description`,
  `type`, or `scope` is skipped without error, so it disappears from the Index
  with no diagnostic. Operators discover the gap only when downstream lookups
  fail to find the ID.
- Baseline title normalization only fires for folder names listed in the
  `TYPE_SUFFIX` constant. Snippets in unrecognized baseline folders get no
  title rewrite, producing inconsistent presentation.
- Project-slug path rewriting is a literal string substitution: `docs/global/`
  becomes `docs/` in the rendered index so the entry is portable to
  `~/.teleclaude/docs/`. Paths in the Index are NOT the working-tree paths;
  resolving back to a real file requires the reader to know which root applies.
- Third-party index generation runs a parallel `.md` flow alongside the
  `.yaml` flow that is likely vestigial. Shedding candidate for v2.
