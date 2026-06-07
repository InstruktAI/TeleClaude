---
id: 'project/spec/feature/context/lifecycle-marker-reconciliation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Integration-time clearing of delivered_by slugs from pending snippets when a delivery slug reaches delivered todo status.'
---

# Lifecycle Marker Reconciliation — Spec

## Required reads

- @docs/project/spec/domain/context.md
- @docs/project/spec/feature/context/snippet-frontmatter-validation.md

## What it is

Lifecycle marker reconciliation keeps documentation-first metadata aligned
with todo delivery. A pending snippet carries a `delivered_by` list of todo
slugs. When the integrator is about to commit a delivered candidate, it
pre-applies the current slug as delivered, reconciles only snippets that
reference that slug, and stages the resulting snippet writes in the integration
worktree before the merge commit prompt is returned.

The reconciler clears the delivered slug from `delivered_by`. If every listed
slug is now delivered, `delivered_by` is removed entirely and the snippet
becomes the current platform contract. If some slugs remain, those are
rewritten as the new `delivered_by` list and the snippet stays pending.
`telec sync` validates snippet shape and builds/deploys indexes; it does not
perform delivery-driven snippet mutations.

## Canonical fields

### Use cases

```
Scenario: All delivered_by slugs are delivered by the current candidate
  Given a snippet with delivered_by ["alpha", "beta"]
  And the todo status map reports "alpha" delivered
  And the current integration candidate is "beta"
  When the candidate merge succeeds in the integration worktree
  Then reconciliation treats "beta" as delivered before writing
  And delivered_by is removed from frontmatter
  And the snippet path is staged before the commit prompt is returned
```

```
Scenario: Some delivered_by slugs are still pending
  Given a snippet with delivered_by ["alpha", "beta"]
  And the current integration candidate is "alpha"
  And "beta" is not delivered
  When reconciliation runs in the integration worktree
  Then delivered_by is rewritten to ["beta"]
  And the snippet path is staged with the candidate merge
```

```
Scenario: Candidate-scoped reconciliation
  Given one snippet references the current candidate slug
  And another unrelated snippet is stale but does not reference the candidate
  When integration reconciliation runs
  Then only the snippet that references the candidate may be rewritten
  And unrelated stale flips are not folded into this delivery commit
```

```
Scenario: Conflict-resolved merge stages snippet reconciliation
  Given a candidate merge was conflicted
  And the operator has resolved conflicts but not yet committed
  When the integration state machine re-prompts for the conflict-resolution commit
  Then candidate-scoped snippet reconciliation runs
  And the reconciled snippet paths are staged before the conflict prompt is returned
```

```
Scenario: Staging failure aborts the merge prompt
  Given integration reconciliation rewrote one or more snippet files
  And the staging step fails for a reconciled snippet path
  When the merge flow prepares the commit prompt
  Then the flow returns a reconcile-staging-failed signal
  And the operator is not prompted to commit until staging succeeds
```

### Cross-context references

- workflow — owns todo status; the integrator pre-applies the current slug
  as `delivered` because delivery bookkeeping has not run yet.
- context — owns snippet frontmatter parse/render primitives used by lifecycle
  callers.

## Known caveats

- Reconciliation is candidate-scoped at write time. It deliberately avoids
  cleaning unrelated stale snippets.
- When the last slug is cleared, `delivered_by` is removed entirely — no
  `status` field is written.
