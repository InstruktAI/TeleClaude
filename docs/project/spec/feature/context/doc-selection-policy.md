---
description: 'Pure-function curation of doc snippets by role visibility, taxonomy areas/domains, scope, baseline manifest anchoring, and target-slug filter.'
visibility: 'public'
---

# Doc Selection Policy — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

<!-- planned-change:docs-tier-layering -->
The Selection policy is the single pure-function composition point for every
filter that narrows the Index down to the snippets a caller actually wants.
Visibility (role gating), taxonomy areas, business domains, scope (global vs.
project), baseline-manifest anchoring, and target-slug filtering all flow
through one place. Given the same Index and the same inputs, the policy
produces a byte-identical set of snippet IDs every time. This determinism is
what lets the retrieval flow be cached, replayed, and reasoned about.
<!-- change:docs-tier-layering -->
The Selection policy is the single pure-function composition point for every
filter that narrows the Index down to the snippets a caller actually wants.
Visibility, taxonomy areas, business domains, scope across the four tiers,
baseline-manifest anchoring, target-slug filtering, and the tier selectors all
flow through one place. Visibility is resolved against the caller's declared
relationships rather than their platform role alone: where a relationship
exists the tier is read in full, and where none exists the snippet's own
public-or-internal declaration is the only gate. Given the same Index and the
same inputs, the policy produces a byte-identical set of snippet IDs every
time. This determinism is what lets the retrieval flow be cached, replayed, and
reasoned about.
<!-- /planned-change:docs-tier-layering -->

## Canonical fields

### Use cases

<!-- planned-change:docs-tier-layering -->
```
Given a caller with a non-admin role
When the Selection policy resolves visibility
Then only snippets with visibility: public are included
And visibility: internal snippets are excluded
```
<!-- change:docs-tier-layering -->
#### UC-DSP6: Without a relationship, the snippet's own declaration is the gate

```
Given an agent session running under the identity of a person who is not a platform administrator
And a tier that identity holds no declared relationship to
When the Selection policy resolves visibility for that tier
Then only snippets declaring themselves public are included
And snippets declaring themselves internal are excluded
```
<!-- /planned-change:docs-tier-layering -->

```
Given a caller with the admin role
When the Selection policy resolves visibility
Then snippets of every visibility (public and internal) are included
```

<!-- planned-change:docs-tier-layering -->
```
Given an anonymous caller with no resolved identity
When the Selection policy resolves visibility
Then the caller is treated as non-admin and only public snippets are returned
```
<!-- change:docs-tier-layering -->
#### UC-DSP7: An agent session with no resolvable identity receives the outsider's view

```
Given an agent session whose identity cannot be resolved
When the Selection policy resolves the read
Then the session holds no relationship to any tier
And only snippets declaring themselves public are returned
And the absent identity never widens the read
```
<!-- /planned-change:docs-tier-layering -->

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

<!-- planned:docs-tier-layering -->
#### UC-DSP19: Retrieving a discovered identity stays open to its discoverer

```
Given an agent session running under the identity of a person who is not a platform administrator
And discovery has returned an identity from a tier that session is permitted to read
When the session retrieves that identity
Then the snippet content is returned
And no tier authorization is required
```
<!-- /planned:docs-tier-layering -->

<!-- planned-change:docs-tier-layering -->
```
Given a snippet ID whose prefix matches a known project slug in the cross-project catalog
When the caller references that ID without --projects
Then the cross-project Source is loaded
And visibility gating still applies
```
<!-- change:docs-tier-layering -->
#### UC-DSP18: Reaching a tier by snippet identity meets the selector rule

```
Given a snippet ID whose prefix matches a known project slug in the cross-project catalog
And that Source is not already in the caller's assembled catalogs
And the caller is authorized to name a tier explicitly
When the caller references that ID without a selector
Then the cross-project Source is loaded
And visibility gating still applies
```
<!-- /planned-change:docs-tier-layering -->

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

<!-- planned-change:docs-tier-layering -->
```
Given --project <slug> matching a registered project in the cross-project catalog
When the Selection policy applies the project filter
Then only snippets whose source project is <slug> are returned
And global snippets and the current project's snippets are excluded
And the filter composes with --areas, --domains, --baseline-only, --scope, and --target
```
<!-- change:docs-tier-layering -->
```
Given --project <slug> matching a registered project in the cross-project catalog
And the caller is authorized to name a tier explicitly
When the Selection policy applies the project filter
Then only snippets whose source project is <slug> are returned
And global snippets and the current project's snippets are excluded
And the filter composes with --areas, --domains, --baseline-only, --scope, and --target
```
<!-- /planned-change:docs-tier-layering -->

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

<!-- planned:docs-tier-layering -->
#### UC-DSP8: Read scope follows the caller, not the working directory

```
Given an agent session invoking documentation discovery from two different directories under one resolved identity
When the Selection policy resolves what that identity is permitted to see
Then the permitted set is identical in both invocations
And the working directory determines only which project's material is offered by default
```

#### UC-DSP9: An agent session reads its own person tier in full

```
Given an agent session whose identity resolves to a registered person
When the Selection policy resolves the read
Then that person's own tier is included in full without the session naming it
And no declaration on those snippets withholds them from their owner
```

#### UC-DSP10: Belonging to a company opens that company's material in full

```
Given an agent session running under the identity of a person holding a declared relationship to a company
When the Selection policy resolves that company's tier
Then every snippet of that company is included regardless of its own visibility declaration
And the role that person holds in that company does not change what is included
```

#### UC-DSP11: A project's owning company is read at the caller's own relationship

```
Given an agent session working in a project that declares an owning company
And the session's identity holds no declared relationship to that company
When the Selection policy resolves that company's tier
Then only snippets declaring themselves public are included
And the project's declaration of its owner still brings that company's tier into scope
```

#### UC-DSP12: Assignment opens a project; company membership alone does not

```
Given an agent session running under the identity of a person holding a declared relationship to a company that owns several projects
And that person is assigned to one of those projects
When the Selection policy resolves the caller's project set
Then the assigned project enters that set and is read in full
And the company's other projects do not enter it
```

#### UC-DSP13: A platform administrator reaches any named tier

```
Given an agent session running under the identity of a platform administrator
And the session names a person, a company, or a project tier explicitly
When the Selection policy resolves the request
Then that named tier is returned in full
```

#### UC-DSP17: A non-administrator is refused every tier selector

```
Given an agent session running under the identity of a person who is not a platform administrator
And the session reaches for a tier outside its derived scope, by selector or by an identity its assembled catalogs do not contain
When the Selection policy resolves the request
Then the reach is refused before the named tier is looked up
And the refusal does not fall back to a narrower read of that tier
And the refusal is identical whether or not the named tier exists
```

#### UC-DSP14: Membership in several companies stays unambiguous

```
Given an agent session running under the identity of a person holding declared relationships to more than one company
And two of those companies publish material on the same subject
When the Selection policy resolves the read
Then each company's material remains separately addressable
And neither company's material shadows or displaces the other's
```

#### UC-DSP15: Scope filter keeps only person snippets

```
Given an agent session passing --scope person
When the Selection policy applies the scope filter
Then only snippets in the person tier are returned
And snippets of every other tier are excluded
```

#### UC-DSP16: Scope filter keeps only company snippets

```
Given an agent session passing --scope company
When the Selection policy applies the scope filter
Then only snippets in the company tier are returned
And snippets of every other tier are excluded
```
<!-- /planned:docs-tier-layering -->

### Cross-context references

- **identity** — terminal-session role is resolved upstream by the CLI and
  passed in; the predicate composition uses it to filter visibility.
- **config** — supplies the registered publishers' `business.publishes`
  declarations (their union is the valid-domain set used for cross-project ID
  classification), the project catalog of known project slugs, and the
  `project_slug` that determines which IDs are "own" vs. "cross-project".

<!-- planned:docs-tier-layering -->
- **identity** — the resolved caller's person identity, not only their platform
  role, is the input from which read scope is derived.
- **config** — supplies the caller's declared company relationships and project
  assignments, and each project's declaration of its owning company. This policy
  reads those declarations and owns none of them.
<!-- /planned:docs-tier-layering -->

## Known caveats

<!-- planned-change:docs-tier-layering -->
- Snippet visibility defaults to `internal` when frontmatter omits the field.
  Public exposure is an explicit opt-in, not the default — so a freshly
  authored snippet without `visibility: public` is invisible to non-admin
  callers until the field is added.
<!-- change:docs-tier-layering -->
- Snippet visibility defaults to `internal` when frontmatter omits the field.
  Public exposure is an explicit opt-in, not the default — so a freshly
  authored snippet without `visibility: public` is invisible to callers holding
  no relationship to its tier until the field is added. Callers who do hold a
  relationship read the tier in full and are unaffected by the default.
<!-- /planned-change:docs-tier-layering -->
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
