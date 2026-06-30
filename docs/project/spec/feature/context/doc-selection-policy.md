---
description: 'Pure-function curation of doc snippets by role visibility, taxonomy areas/domains, scope, baseline manifest anchoring, and target-slug filter.'
visibility: 'public'
---

# Doc Selection Policy — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

The Selection policy is the single pure-function composition point for every
filter that narrows the Index down to the snippets a caller actually wants.
Visibility (role gating), taxonomy areas, business domains, scope (global vs.
project), baseline-manifest anchoring, and target-slug filtering all flow
through one place. Given the same Index and the same inputs, the policy
produces a byte-identical set of snippet IDs every time. This determinism is
what lets the retrieval flow be cached, replayed, and reasoned about.

## Canonical fields

### Use cases

```
Given a caller with a non-admin role
When the Selection policy resolves visibility
Then only snippets with visibility: public are included
And visibility: internal snippets are excluded
```

```
Given a caller with the admin role
When the Selection policy resolves visibility
Then snippets of every visibility (public and internal) are included
```

```
Given an anonymous caller with no resolved identity
When the Selection policy resolves visibility
Then the caller is treated as non-admin and only public snippets are returned
```

```
Given a global snippet under ~/.teleclaude/docs/ whose ID is project-prefixed
When the Selection policy filters the global tree
Then the snippet is excluded
And only general/* or domain-prefixed IDs survive
```

```
Given --areas policy passed by the caller
When the Selection policy applies the type filter
Then only snippets with frontmatter type: policy are returned
```

```
Given no --domains flag
When the Selection policy resolves the candidate set
Then every global snippet stays universally visible and the project's own snippets are included
And the cross-project domain prefixes are the union of registered publishers' business.publishes
```

```
Given --baseline-only is set
When the Selection policy applies baseline anchoring
Then it loads the relevant baseline.md manifest(s) and keeps only IDs reachable via @-refs
```

```
Given --target <slug> is set
When the Selection policy applies the target filter
Then only snippets whose delivered_by includes <slug> are returned
And third-party snippets are silenced
```

```
Given a snippet ID whose prefix matches a known project slug in the cross-project catalog
When the caller references that ID without --projects
Then the cross-project Source is loaded
And visibility gating still applies
```

#### UC-DSP1: Scope filter keeps only global snippets

```
Given --scope global passed by the caller
When the Selection policy applies the scope filter
Then only snippets with scope global are returned
And project-scoped snippets are excluded
```

#### UC-DSP2: Scope filter keeps only project snippets

```
Given --scope project passed by the caller
When the Selection policy applies the scope filter
Then only snippets with scope project are returned
And global-scoped snippets are excluded
```

#### UC-DSP3: Project filter keeps only the queried project's snippets

```
Given --project <slug> matching a registered project in the cross-project catalog
When the Selection policy applies the project filter
Then only snippets whose source project is <slug> are returned
And global snippets and the current project's snippets are excluded
And the filter composes with --areas, --domains, --baseline-only, --scope, and --target
```

#### UC-DSP4: Project filter on an unknown slug returns nothing

```
Given --project <slug> matching no project in the cross-project catalog
When the Selection policy applies the project filter
Then no snippets are returned
```

#### UC-DSP5: Domains filter keeps only snippets in the requested published domains

```
Given --domains <domain> passed by the caller
When the Selection policy applies the domains filter
Then only snippets whose domain is in the requested set are returned
And snippets in other domains, including structural scopes general and project, are excluded
And third-party entries are silenced
```

### Cross-context references

- **identity** — terminal-session role is resolved upstream by the CLI and
  passed in; the predicate composition uses it to filter visibility.
- **config** — supplies the registered publishers' `business.publishes`
  declarations (their union is the valid-domain set used for cross-project ID
  classification), the project catalog of known project slugs, and the
  `project_slug` that determines which IDs are "own" vs. "cross-project".

## Known caveats

- Snippet visibility defaults to `internal` when frontmatter omits the field.
  Public exposure is an explicit opt-in, not the default — so a freshly
  authored snippet without `visibility: public` is invisible to non-admin
  callers until the field is added.
- Every published global domain is universally visible to every project; there
  is no per-project global-domain gate. The set of valid domains is the union of
  the registered publishers' `business.publishes`. The `--domains` flag still
  narrows a listing to requested domains on demand.
- Cross-project snippet `delivered_by` slugs are NOT normalized against the
  consuming project's todo list. A snippet that references a slug from a
  foreign project appears in the consuming project's index with a phantom
  dependency that no local lifecycle will ever resolve.
- Baseline manifest resolution matches snippets by `@`-ref file path; ID
  matching is secondary. Refactoring a snippet's filesystem path without
  updating the manifest silently drops it from the baseline set.
