---
id: 'project/spec/feature/context/baseline-snippet-manifests'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Curated baseline.md files of @-refs that anchor the always-loaded snippet set per scope.'
---

# Baseline Snippet Manifests — Spec

## Required reads

- @docs/project/spec/domain/context.md
- @docs/project/spec/feature/context/doc-selection-policy.md

## What it is

Each scope (global, project) can declare a curated "always-load" baseline set
of snippets via a `baseline.md` manifest. The manifest contains nothing but
`@`-refs to Source files — no prose, no frontmatter, no H1. The Selection
policy's `--baseline-only` mode reduces the visible Index to exactly the
snippets reachable from these manifests, giving callers a known minimum
context floor for any task. Sync auto-infers `type` and `scope` for snippets
under a `baseline/` folder so authors do not have to hand-write the
boilerplate frontmatter.

## Canonical fields

### Use cases

```
Given a baseline manifest at docs/project/baseline.md
When validation runs during sync
Then only @-ref lines (and comments) are accepted
And any prose, H1, frontmatter, or non-ref content fails validation
```

```
Given --baseline-only is passed to the Selection policy
When the global manifest exists at docs/global/baseline.md and a project manifest exists
Then both manifests are loaded
And the visible set collapses to snippets reachable via their @-refs
```

```
Given a snippet file under docs/global/baseline/policy/some-rule.md
When sync builds the index
Then type is auto-inferred as "policy" from the folder name
And scope is set to global
And the rendered index path substitutes ~/.teleclaude/docs/ for docs/global/
```

```
Given a tracked baseline file whose symlink is broken or self-pointing
When sync runs _repair_broken_docs_links
Then the file is restored from git HEAD
And the symlink is rewritten to a valid target
```

```
Given a tracked file that was never committed to git
When the symlink is broken and _repair_broken_docs_links runs
Then the restore attempt silently fails
And no warning is surfaced to the operator
```

```
Given a baseline manifest entry pointing at a snippet with Required reads
When --baseline-only is applied
Then only the manifest-referenced snippet is included
And its Required reads dependencies are NOT auto-pulled into the baseline set
```

### Implementation pointers (v1)

- `teleclaude/resource_validation/_snippet.py:374-390` — `_validate_baseline_index()` ref-only enforcement
- `teleclaude/context_selector.py:366-402` — `_load_baseline_ids()` manifest resolver
- `teleclaude/context_selector.py:641-660` — `_apply_baseline_filter()`
- `teleclaude/docs_index.py:524-557` — baseline path/type inference at index build time
- `teleclaude/sync.py:124-160` — `_repair_broken_docs_links()` symlink repair pass

### Cross-context references

- None direct. The baseline manifest concept is wholly owned by the context
  bounded context; consumers (Selection policy, Index build, Sync) all live
  inside the same context boundary.

## Known caveats

- Symlink repair is hardcoded to a small `tracked_docs_files` tuple
  (`docs/global/baseline.md` and a few siblings). Adding a new tracked
  baseline-adjacent file requires a code change to extend the tuple — there
  is no config-driven registration.
- Symlink repair reads from git HEAD silently. If the tracked file was never
  committed, restoration fails with no warning, leaving the operator with a
  broken link and no diagnostic.
- Baseline manifests do NOT enforce dependency closure. A manifest entry
  whose snippet declares Required reads will not auto-include those reads in
  the baseline-only set, so callers under `--baseline-only` get less context
  than they may expect.
- Baseline `type` inference relies on the folder name matching a known type
  string. Snippets placed in baseline folders with unrecognized names get no
  inferred type and may be skipped at index build for failing frontmatter
  checks.
