---
description: 'The publication pipeline: what each phase does, how per-project capability gating scopes it, and the contract each phase carries.'
visibility: 'public'
---

# Sync Pipeline Orchestration — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is


Publication is Context's internal maintenance primitive for promoting validated
recorded source into deployed agent runtime outputs. Commit or merge
maintenance supplies the recorded range; publication resolves committed source,
rebuilds derived indexes, and distributes runtime artifacts. It never reads the
caller's current working tree and has no operator-facing command.

Publication does not mutate doc snippets in response to todo delivery state;
delivery-driven `delivered_by` reconciliation belongs to the integration
lifecycle before the delivery commit is made.

The publication pipeline is:

1. **Resolve activated source** — materialize the recorded tip for the
   triggering project and retain every other publisher at its previously
   activated revision.
<!-- planned-change:stale-sync-retry-regresses-global-publication -->
2. **Build indexes** — derive indexes from the triggering project's recorded
   snapshot for publication. Write portable derived indexes to its canonical
   checkout only while that checkout's latest commit is the recorded tip;
   recheck the tip after installation and retain the prior local catalog if
   the ref advanced during the write. Replay of an older range leaves its
   local indexes untouched.
3. **Distribute** — compose and atomically deploy the capability-gated runtime
   outputs from those snapshots.
<!-- change:stale-sync-retry-regresses-global-publication -->
2. **Build indexes** — derive indexes from the triggering project's recorded
   snapshot for publication and write portable derived indexes to its
   canonical checkout.
3. **Distribute** — compose and atomically deploy the capability-gated runtime
   outputs from those snapshots, then record the recorded tip as the canonical
   checkout's published generation.

A canonical checkout's published generation is the recorded tip of its latest
successful publication. Publication compares against it once it holds
publication serialization. A recorded tip that is a strict ancestor of the
published generation is superseded: its publication runs no index or
distribution phase, leaves the canonical checkout's indexes and every deployed
runtime output unchanged, and reports a superseded outcome. Any other recorded
tip publishes and becomes the published generation, so a replay of a range
whose later successors have not yet published advances deployment rather than
waiting on them.
<!-- /planned-change:stale-sync-retry-regresses-global-publication -->


Normal and recovery publication consume a recorded commit that already passed
its commit gate. Initial activation, when used, validates a clean recorded
`HEAD` and blocks on every finding before publication. There is no bypass,
warn-and-publish mode, or working-tree entrypoint.


Initial-activation validation findings are stdout text grouped by error code
and reason; there is no machine-readable output channel today.

## Canonical fields

Each per-project publication phase runs only when the recorded declaration
subscribes the capability that owns it
(`project/spec/feature/config/project-capability-manifest`). Snippet index
building and documentation publication run only under a subscribed `docs`;
agent-artifact transpilation and deployment run only under a subscribed
`agents`. A project subscribing neither runs no per-project phase.


Project-setup convergence is not a publication phase; it is contracted in
`project/spec/feature/reconciliation/project-plumbing-convergence`.


The behavioral contract for this gating lives in
`project/spec/feature/config/project-capability-manifest` — `UC-CFG-CAP-17` (an unsubscribed
`docs` capability leaves the snippet pipeline idle) and `UC-CFG-CAP-18` (an unsubscribed `agents`
capability leaves artifact distribution idle). Those scenarios are the single inventory for this
behavior; this spec references them rather than restating them.

### Use cases


#### UC-SPO23: Publication reads committed source

```gherkin
Given a recorded canonical commit whose changed paths owe publication
And another registered repository has a newer committed or uncommitted source state that has not run its own publication action
When the internal publication action runs for that recorded range
Then the triggering repository contribution advances to the recorded tip
And every other repository contribution remains at its previously activated revision
And no unactivated source appears in a deployed output
```

#### UC-SPO22: A legacy documentation-root symlink does not strand deployment

```gherkin
Given recorded-commit publication starts with valid documentation sources
And the deployed documentation root is a legacy symlink
When the replacement documentation snapshot is published
Then publication exits zero
And the deployed documentation root is a real directory containing the complete replacement snapshot
And no displaced legacy symlink remains beside the deployed root
```






#### UC-SPO24: Unrecorded source cannot publish

```gherkin
Given a caller has a working tree but supplies no valid recorded commit range
When it requests publication
Then publication is rejected before index build or distribution
And no runtime output changes
```




<!-- planned-change:stale-sync-retry-regresses-global-publication -->
#### UC-SPO25: Recovery publishes the original recorded range

```gherkin
Given publication failed for a recorded commit range
And a later commit or working-tree edit exists
When maintenance replays the publication action for the failed range
Then publication resolves the original committed input
And the later source does not replace it
And the replay reports its terminal outcome for that original range
```
<!-- change:stale-sync-retry-regresses-global-publication -->
#### UC-SPO25: Recovery publishes the original recorded range

```gherkin
Given publication failed for a recorded commit range
And no later commit's source has been published, while a later commit or working-tree edit exists
When an agent replays the publication action for the failed range
Then an agent retrieving the deployed documentation reads the original committed input
And the later source does not replace it
And the replaying agent receives the terminal outcome for that original range
```
<!-- /planned-change:stale-sync-retry-regresses-global-publication -->

<!-- planned:stale-sync-retry-regresses-global-publication -->
#### UC-SPO28: A superseded replay leaves newer published output in place

```gherkin
Given publication failed for a recorded commit range
And a later canonical-main commit's source has since been published
When an agent replays the publication action for the failed range
Then an agent retrieving documentation, commands, or skills reads the later published source
And an agent's local documentation retrieval still lists the later published catalog
And the replaying agent receives a superseded terminal outcome for the original range
And the failed action no longer awaits the agent's recovery
```
<!-- /planned:stale-sync-retry-regresses-global-publication -->

#### UC-SPO26: The working-tree publication command is absent

```gherkin
Given an operator invokes telec sync
When the root command parser resolves the requested command
Then the invocation is rejected as an unknown command
And no validation, index build, distribution, or runtime-output write starts
```



#### UC-SPO27: Delivery reconciliation is published as part of its commit

```
Scenario: Delivery reconciliation is part of the published commit
  Given integration stages snippet lifecycle reconciliation in its delivery commit
  When canonical-main maintenance publishes that recorded range
  Then publication reads the already-reconciled committed source
  And publication performs no authored source markdown mutation
```

#### UC-SPO16: Publication performs only its own phases

```gherkin
Given a reachable project's derived indexes and runtime artifacts are not current for its recorded source
And that project's configuration document is not yet at the current schema
When recorded-commit maintenance publishes that project
Then the derived indexes and runtime artifacts are republished
And the reachable project's configuration document is still not migrated
```

#### UC-SPO4: A slug-worktree commit publishes nothing

```
Scenario: UC-SPO4 A slug-worktree commit publishes nothing
  Given an agent records a commit in a slug worktree rather than canonical main
  When the worktree commit completes
  Then no main-only publication action runs
  And no documentation or agent-artifact runtime output changes
```

#### UC-SPO17: A deployment composes every participating tier's documentation

```
Given a company or person tier whose declaration records participation in the documentation surface
When committed-state publication activates the platform home's recorded source
Then that tier's documentation is composed into the published snapshot exactly as a registered project's is
And no global agent-artifact publication path opens from the tier's home
```

#### UC-SPO21: A commit under a participating tier's home republishes the snapshot

```
Given the platform home carries TeleClaude's post-commit maintenance
And a person's or company's documentation home inside it participates in the documentation surface
When a documentation source under that home is committed
Then the commit-boundary maintenance republishes the deployed documentation snapshot
And the tier's committed material is in that snapshot, exactly as a registered project's would be
And a saved but uncommitted change under the home deploys nothing
```

#### UC-SPO12: Concurrent publications expose complete documentation generations

```gherkin
Given an agent validates a documentation reference on a host before that reference has been deployed
And two recorded commit ranges owe publication on the same host
When their publication actions overlap
Then validation resolves the reference from its registered publisher source
And validation does not depend on a deployed documentation tree existing
And each publication exposes a complete deployed documentation-root generation
And no validator reports a valid reference missing solely because publication is rebuilding that tree
```

#### UC-SPO13: Interrupted serialization does not permanently block publication

```gherkin
Given a publication action stops while it owns host-wide serialization
When maintenance later performs another publication action
Then the later action can acquire serialization after the abandoned ownership is released
And an action that cannot acquire serialization within the bounded wait exits non-zero with an explicit failure
```

#### UC-SPO14: Runtime documentation readers observe complete snapshots

```gherkin
Given a runtime reader opens deployed documentation while publication activates a replacement
When the publication completes
Then the reader observes either the complete prior snapshot or the complete replacement snapshot
And the deployed documentation root and its published domains are never absent or partially composed
```

#### UC-SPO15: Source validation works before first deployment

```gherkin
Given a registered publisher owns a referenced documentation domain
And no deployed documentation tree has been created on the host
When an agent validates an authored artifact or snippet reference to that domain
Then validation resolves the reference in the owning publisher source tree
And validation reports a finding only when that source target is missing
But a reference naming that domain's generated baseline bundle resolves against the deployed generation
And its absence before first deployment is not a finding
```


### Cross-context references

- **workflow / integration** — own todo delivery state and delivery-time
  `delivered_by` reconciliation.
- **config** — supplies project root and Mother-project resolution consumed by
  the distribution step.
- **agent_runtime** — phase 3's distribution step deploys to the agent runtime
  boundary.

## Known caveats

<!-- planned-change:stale-sync-retry-regresses-global-publication -->
- Publication is idempotent at the authored-source layer: it builds indexes
  from the recorded snapshot and places published domain bundles inside the
  deployed generation. It writes gitignored `index.yaml` files with canonical
  checkout paths only when the recorded tip still matches that checkout's
  latest commit. The host documentation lease covers the checkout write and
  every publication action, including maintenance from a person's direct Git
  commit or merge. Git may advance its ref while a publication holds that
  lease, so the writer rechecks the tip and retains the prior local catalog
  if it changed; the later commit's maintenance writes its own catalog when
  that action succeeds. Replaying an older range never replaces a newer local
  index; it still publishes runtime output from the original recorded range.
  Publication never mutates authored source snippets or uses uncommitted files.
<!-- change:stale-sync-retry-regresses-global-publication -->
- Publication is idempotent at the authored-source layer: it builds indexes
  from the recorded snapshot and places published domain bundles inside the
  deployed generation. It writes gitignored `index.yaml` files with canonical
  checkout paths whenever its recorded tip becomes the published generation,
  including after later commits that owe no publication. The host
  documentation lease covers the checkout write and every publication action,
  including maintenance from a person's direct Git commit or merge, so a later
  commit's publication runs after an earlier one releases it and writes its
  own catalog when that action succeeds. Replaying a superseded range changes
  neither the local index nor runtime output. Publication never mutates
  authored source snippets or uses uncommitted files.
<!-- /planned-change:stale-sync-retry-regresses-global-publication -->


- Deployed artifacts reflect committed state. Between a save and its commit, the
  deployed tree is the previous commit's.


- Project bootstrap converges declarations, filters, and hooks but publishes no
  working-tree source. The first validated canonical commit activates the
  project's subscribed outputs. An explicit initial activation, when used,
  requires a clean recorded `HEAD` and blocking validation.
- Publication fails explicitly when its distribution implementation is
  unavailable; a recorded activation never reports success after omitting a
  runtime-output phase.
