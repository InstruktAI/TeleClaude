---
description: 'The telec sync pipeline: what each phase does, how per-project capability gating scopes it, and the contract each phase carries.'
visibility: 'public'
---

# Sync Pipeline Orchestration — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is


`telec sync` is the operator-facing command that promotes git-tracked Source
into Deployed agent runtime outputs. Its responsibility is synchronization:
validate authored source shape, rebuild derived indexes, and distribute
runtime artifacts. It does not mutate doc snippets in response to todo
delivery state; delivery-driven `delivered_by` reconciliation belongs to the
integration lifecycle before the delivery commit is made.

The sync pipeline is:

1. **Validate** — run snippet, artifact, and jobs-config validators.
2. **Build indexes** — write fresh derived doc indexes from source snippets.
3. **Distribute** — invoke the distribution step in deploy mode.


<!-- planned-change:retire-docs-watcher -->
Validation always blocks: any finding stops the pipeline and `telec sync` exits
non-zero — there is no warn-and-pass mode. Each flag skips one phase:

- `--skip-deploy` — validate only; return after validation with no index build,
  symlink repair, or distribution. The read-only gate for pre-commit / CI / lint;
  it must not mutate the host's agent-runtime dirs, and it still blocks on findings.
- `--skip-validation` — skip validation entirely and deploy without blocking.
  Hidden and role-gated to the docs watcher (live reload must never stall on a
  mid-edit state); the commit gate is the real validation contract. Not for agents.
<!-- change:retire-docs-watcher -->
Validation always blocks: any finding stops the pipeline and `telec sync` exits
non-zero — there is no warn-and-pass mode, and no flag skips a phase. Every
invocation validates, then deploys.

`telec sync` has no ambient caller. Deployment reaches the same artifacts at the
commit boundary, and the command stays directly invocable for the runs no commit
triggers: a fresh clone, a newly registered project, or recovery after a failed
run. Its callers are the post-commit hook, project bootstrap, and deliberate
invocation.
<!-- /planned-change:retire-docs-watcher -->


Validation findings are stdout text grouped by error code and reason; there is
no machine-readable output channel today.

## Canonical fields

Each per-project phase runs only when the project subscribes the capability that
owns it (`project/spec/feature/config/project-capability-manifest`). Snippet
validation, index building, and documentation publication run only under a
subscribed `docs`; agent-artifact transpilation and deployment run only under a
subscribed `agents`. A project subscribing neither runs no per-project phase.


Project-setup convergence is not a sync phase; it is contracted in
`project/spec/feature/reconciliation/project-plumbing-convergence`.


The behavioral contract for this gating lives in
`project/spec/feature/config/project-capability-manifest` — `UC-CFG-CAP-17` (an unsubscribed
`docs` capability leaves the snippet pipeline idle) and `UC-CFG-CAP-18` (an unsubscribed `agents`
capability leaves artifact distribution idle). Those scenarios are the single inventory for this
behavior; this spec references them rather than restating them.

### Use cases


```
Scenario: Full sync on a clean Mother project checkout
  Given the project source is git-tracked and validates cleanly
  When the operator runs telec sync
  Then snippet, artifact, and jobs-config validators run once
  And the index-build phase produces a fresh index
  And broken or self-pointing tracked docs symlinks are repaired
  And the distribution step is invoked in deploy mode
And the run exits zero
```

#### UC-SPO22: A legacy documentation-root symlink does not strand deployment

```gherkin
Given an agent invokes telec sync in deploy mode with valid documentation sources
And the deployed documentation root is a legacy symlink
When the replacement documentation snapshot is published
Then the invocation exits zero
And the deployed documentation root is a real directory containing the complete replacement snapshot
And no displaced legacy symlink remains beside the deployed root
```



<!-- planned-change:retire-docs-watcher -->
```
Scenario: --skip-deploy validates but produces no derived outputs
  Given the operator wants to validate without deploying
  When telec sync --skip-deploy is invoked
  Then validators run once
  And no index build, symlink repair, or distribution step runs
And the run exits zero only when validation is clean
```
<!-- change:retire-docs-watcher -->
<!-- /planned-change:retire-docs-watcher -->



<!-- planned-change:retire-docs-watcher -->
```
Scenario: Validation findings always block
  Given snippet, artifact, or jobs-config validation reports a finding
  When telec sync (with or without --skip-deploy) is invoked
  Then the findings are printed grouped by error code and reason
  And the pipeline aborts before any deploy
And the run exits non-zero
```
<!-- change:retire-docs-watcher -->
#### UC-SPO19: Validation findings always block

```gherkin
Given snippet, artifact, or jobs-config validation reports a finding
When telec sync is invoked
Then the findings are printed grouped by error code and reason
And the pipeline aborts before any deploy
And the run exits non-zero
```
<!-- /planned-change:retire-docs-watcher -->



<!-- planned-change:retire-docs-watcher -->
#### UC-SPO18: The docs watcher bypasses validation to live-reload

```gherkin
Given the docs watcher authorizes the hidden --skip-validation flag
When telec sync --skip-validation is invoked
Then validation is skipped entirely
And the pipeline builds indexes and distributes
And the run never blocks on source validity
```
<!-- change:retire-docs-watcher -->
<!-- /planned-change:retire-docs-watcher -->

<!-- planned-change:retire-docs-watcher -->
```
Scenario: A non-watcher caller is rejected from bypassing validation
  Given a caller that is not the docs watcher
  When it invokes telec sync --skip-validation
  Then the command is rejected and exits non-zero
And no deploy occurs
```
<!-- change:retire-docs-watcher -->
#### UC-SPO20: An unknown flag is rejected

```gherkin
Given an operator invokes telec sync with a flag the command does not declare
When the command parses its arguments
Then the invocation is rejected with the command's usage
And the run exits non-zero
And no validation, index build, or distribution step runs
```
<!-- /planned-change:retire-docs-watcher -->



```
Scenario: Delivery completes before sync
  Given an integration delivery staged snippet lifecycle reconciliation in its merge commit
  When telec sync runs after the delivery
  Then sync validates the already-mutated source
  And sync performs no additional source markdown mutations
```

#### UC-SPO16: Deploy-mode sync performs only its own phases

```gherkin
Given a reachable project's derived indexes and runtime artifacts are not current for the source state
And that project's configuration document is not yet at the current schema
When an agent invokes a deploy-mode synchronization for that project
Then the derived indexes and runtime artifacts are republished
And the reachable project's configuration document is still not at the current schema
```

#### UC-SPO4: Deploy-mode sync is refused from a slug worktree

```
Scenario: UC-SPO4 Deploy-mode sync is refused from a slug worktree
  Given an agent invokes telec sync in deploy mode from a slug worktree (trees/<slug>, not trees/_integration)
  When the pipeline starts
  Then it exits non-zero with an error that docs deployment is not allowed from a slug worktree
<!-- planned-change:retire-docs-watcher -->
  And no validation, index build, symlink repair, or distribution step runs
  And a --skip-deploy run, and deploy-mode sync from the main checkout or the integration worktree, are unaffected
<!-- change:retire-docs-watcher -->
  And no validation, index build, symlink repair, or distribution step runs
  And deploy-mode sync from the main checkout or the integration worktree is unaffected
<!-- /planned-change:retire-docs-watcher -->
```

<!-- planned:docs-tier-layering -->
#### UC-SPO17: A deployment composes every participating tier's documentation

```
Given a company or person tier whose declaration records participation in the documentation surface
When a deployment runs, from whichever of its callers invoked it
Then that tier's documentation is composed into the published snapshot exactly as a registered project's is
And no global agent-artifact publication path opens from the tier's home
```
<!-- /planned:docs-tier-layering -->

<!-- planned:home-tier-commit-maintenance -->
#### UC-SPO21: A commit under a participating tier's home republishes the snapshot

```
Given the platform home carries TeleClaude's post-commit maintenance
And a person's or company's documentation home inside it participates in the documentation surface
When a documentation source under that home is committed
Then the commit-boundary maintenance republishes the deployed documentation snapshot
And the tier's committed material is in that snapshot, exactly as a registered project's would be
And a saved but uncommitted change under the home deploys nothing
```
<!-- /planned:home-tier-commit-maintenance -->

#### UC-SPO12: Concurrent syncs observe a complete documentation deployment

```gherkin
Given an agent validates a documentation reference on a host before that reference has been deployed
And another process requests documentation synchronization on the same host
When the two synchronization runs overlap
Then validation resolves the reference from its registered publisher source
And validation does not depend on a deployed documentation tree existing
And synchronization publishes a complete deployed documentation-root snapshot
And no validator reports a valid reference missing solely because another synchronization is rebuilding that tree
```

#### UC-SPO13: Interrupted serialization does not permanently block synchronization

```gherkin
Given a synchronization run stops while it owns host-wide serialization
When another agent later requests synchronization
Then the later run can acquire serialization after the abandoned ownership is released
And a run that cannot acquire serialization within the bounded wait exits non-zero with an explicit failure
```

#### UC-SPO14: Runtime documentation readers observe complete snapshots

```gherkin
Given a runtime reader opens deployed documentation while synchronization publishes a replacement
When the publication completes
Then the reader observes either the complete prior snapshot or the complete replacement snapshot
And the deployed documentation root and its published domains are never absent or partially composed
```

#### UC-SPO15: Source validation works before first deployment

```gherkin
Given a registered publisher owns a referenced documentation domain
And no deployed documentation tree has been created on the host
When an agent validates an artifact or snippet reference to that domain
Then validation resolves the reference in the owning publisher source tree
And validation reports a finding only when that source target is missing
```


### Cross-context references

- **workflow / integration** — own todo delivery state and delivery-time
  `delivered_by` reconciliation.
- **config** — supplies project root and Mother-project resolution consumed by
  the distribution step.
- **agent_runtime** — phase 3's distribution step deploys to the agent runtime
  boundary.

## Known caveats

- Sync is idempotent at the source markdown layer: it writes the derived,
  gitignored `index.yaml` indexes into the source tree and each published
  domain's `domain-baseline-bundle.md` into the deployed root
  `~/.teleclaude/docs/<domain>/` (not the source tree), but it must not mutate
  authored `docs/**/*.md` snippets.


<!-- planned-change:retire-docs-watcher -->
- `--skip-deploy` exits before index build and symlink repair. Broken tracked
  symlinks may therefore remain broken until a full sync runs.
- `--skip-validation` deploys unvalidated source; it is reserved for the docs
  watcher's live reload, where the commit gate remains the validation contract.
<!-- change:retire-docs-watcher -->
- Deployed artifacts reflect committed state. Between a save and its commit, the
  deployed tree is the previous commit's.
<!-- /planned-change:retire-docs-watcher -->


- Project bootstrap (`telec projects init` / `onboard`, via `sync_bootstrap`)
  validates and reports findings without blocking, then deploys — a human-run,
  one-time setup path distinct from the always-blocking `telec sync` command.
  The commit gate remains the validation contract for ongoing work.
- The distribution step is optional in stripped-down deployments because a
  missing distribution entrypoint silently skips phase 3.
- The v1 CLI namespace is `telec sync`. The v2 target is `telec context sync`.
