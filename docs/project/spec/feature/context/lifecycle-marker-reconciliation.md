---
description: 'Integration-time clearing of delivered_by slugs from pending snippets when a delivery slug reaches delivered todo status.'
visibility: 'public'
delivered_by: [host-scoped-pending-markers]
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

#### UC-LMR1: Delivery resolves only the candidate's planned-change block

```
Given a live parent snippet contains a planned-change block for the current candidate
And the same parent contains a planned-change block for another slug
When delivery reconciliation runs for the current candidate
Then the current candidate's block is replaced by its replacement content
And all three marker lines for the current candidate are removed
And the other slug's planned-change block is left unchanged
And a second reconciliation run makes no further change
```

<!-- planned:host-scoped-pending-markers -->

#### UC-LMR2: Reconciliation is host-scoped — foreign tokens survive a local transition

A marker token is `<slug>@<host>`; a bare token (no `@`) is local/legacy. A delivery,
abandon, orphan-scan, or rename matches a token only when its stripped slug equals the
target slug AND its host is absent or equals the local computer name. A token whose host
names another computer is left byte-for-byte untouched, because that pending todo lives on
another machine and has no local row to drive its deletion.

```
Given a live parent snippet contains a planned block for "feat-x@LocalHost"
And the same parent contains a planned block for "feat-x@RemoteHost"
And the local computer name is "LocalHost"
When delivery reconciliation runs for the local candidate "feat-x"
Then the "feat-x@LocalHost" block is folded into the live contract
And the "feat-x@RemoteHost" block is left unchanged
And no residual-marker error is raised
```

```
Given a snippet carries delivered_by ["feat-x@RemoteHost"]
And the local computer name is "LocalHost"
When the local todo "feat-x" is hard-purged and purge reconciliation runs
Then the "feat-x@RemoteHost" entry is left unchanged
And no snippet write that touches the foreign token is produced
```

<!-- /planned:host-scoped-pending-markers -->

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
