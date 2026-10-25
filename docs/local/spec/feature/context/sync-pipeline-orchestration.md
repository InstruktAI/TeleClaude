---
description: 'The publication pipeline: what each phase does, how per-project capability gating scopes it, and the contract each phase carries.'
visibility: 'public'
---

# Sync Pipeline Orchestration — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

Publication is Context's routine for promoting committed source into deployed
agent runtime outputs. Committed state has passed the commit gate
(`local/projects/teleclaude/design/code-commit`) and is the source of truth, so
publication derives and never validates: it resolves committed source, rebuilds
derived indexes, and distributes runtime artifacts. It never reads a working
tree.

Three entry points run the same routine:

- **Commit-boundary maintenance** — a canonical-main activation whose changed
  paths owe publication publishes the homes it touched
  (`local/projects/teleclaude/spec/feature/integration/post-commit-maintenance`).
  The platform's own project publishes both halves this way, like every other
  project, so a contract committed on its main is readable as soon as that
  activation's maintenance has run.

- **Installation** — on a machine where no project checkout of the platform is
  registered, the install act publishes the platform's published documentation
  and agent artifacts from the release it installed, when the platform home
  does not already record that commit
  (`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`).
  A fresh machine therefore serves the installed release's committed
  documentation and agent artifacts before anything is committed on it. Its
  source is the installed commit, never a project's `main` tip, and it deploys
  that commit even when the home records a different one, so the deployed
  documentation matches the installed code. A release is not a home, so the
  install act publishes no local half. It holds the same publication
  serialization, and the install act acts only on its result. Where a project
  checkout of the platform is registered, that checkout publishes the
  platform's documentation and agent artifacts through the other two entry
  points; the installation entry point then publishes nothing and reports that
  the checkout publishes them.

- **`telec sync`** — the on-demand maintenance run
  (`local/projects/teleclaude/spec/feature/integration/on-demand-maintenance`),
  whose publication step publishes the home at the invocation directory and
  every nested home beneath it in the committed tree: in the global home, its
  company and person homes. It runs only from the canonical checkout on its main
  branch, and only when the invocation directory itself holds a
  `teleclaude.yml`; it never resolves a home from a parent directory, and
  anywhere else it refuses and names that requirement. It is an agent command,
  reached by every agent role except the worker, and admits members and admins
  (`local/projects/teleclaude/spec/feature/identity/command-clearance`).

Home vocabulary follows `local/projects/teleclaude/spec/domain/glossary`. Homes are
discovered in the committed tree, never on disk, so a gitignored folder or a
foreign repository is never a home in scope.

Publication does not mutate doc snippets in response to todo delivery state;
delivery-driven `delivered_by` reconciliation belongs to the integration
lifecycle before the delivery commit is made.

The unit of publication is one home. For each home in scope:

1. **Resolve committed source** — while holding publication serialization,
   read the canonical checkout's committed `main` tip, or for the installation
   entry point the installed commit, and materialize it; every other publisher
   keeps its previously activated revision.

2. **Build indexes** — derive the home's indexes from that snapshot and write
   portable derived indexes to the canonical checkout.
3. **Distribute** — compose and atomically deploy the home's capability-gated
   runtime outputs, replacing only that home's contribution, then record the
   tip as that home's published generation.

A home whose build fails — an unreadable declaration, an index that cannot be
built, an entrypoint that cannot be composed — is skipped. Its previous
deployment stays in place, every other home in scope still publishes, and the
home is reported with its build error and with the commit gate's lint findings
over that home's committed files. The findings explain a skip; they never
select what publishes. `telec sync` exits non-zero when any home was skipped.

For maintenance and `telec sync`, the tip is read under serialization, so a
later publication never deploys an older tip than an earlier one. A commit range
decides only whether publication is owed, never what is published. Maintenance
publication of a home that already records the tip changes nothing; `telec sync`
always rebuilds the homes in scope. The installation entry point deploys the
installed commit, whichever generation the home records, and changes nothing
when the home already records that commit.

A Mother publication also refreshes the home entrypoints that inline the
Mother's documentation.

A completed legacy platform-home publication whose historical commit object is
missing remains an explicit provenance failure. A serialized full-root
rebuild through `telec sync` can recover from the home's actual committed main
tip. It records that tip only for homes that publish, preserves previous
deployments for failed homes, and retains the legacy identifiers and read failure
as evidence. Partial recovery remains nonzero; a Mother refresh can refresh
proven homes but still reports the unresolved legacy history. Complete root
reconciliation retires the legacy state. Removed homes are reconciled against
current committed inventory and deployed ownership, without reconstructing the
unavailable tree. Other publishers keep their activated revisions.

There is no working-tree entrypoint and no bypass.

### Installed release publication

The install act selects the commit of the release it installed under
publication serialization; the canonical-main source and location rules above
apply to every project checkout, the platform's own included. A replay of a
failed install publication publishes the commit of the active release; it never
reads a project's local main tip. The installed commit's identity is checked
again before distribution. If the active release changed, publication reports
the conflict and leaves that attempt incomplete.

## Canonical fields

Each per-project publication phase runs only when the committed declaration
subscribes the capability that owns it
(`local/projects/teleclaude/spec/feature/config/project-capability-manifest`). Snippet index
building and documentation publication run only under a subscribed `docs`;
agent-artifact transpilation and deployment run only under a subscribed
`agents`. A project subscribing neither runs no per-project phase.

**Master sources.** Publication reads every `AGENTS.master.md` — the project
master walk and the fixed home master set
(`local/projects/teleclaude/spec/feature/context/agents-master-inflation`)
alike — from the committed source; a master its repository does not track is
never read. The project master walk covers every folder of the committed tree
except tooling folders such as dependency environments and build output. In
the Mother repository it also leaves out TeleClaude's own template tree,
identified by where that tree resolves rather than by a folder name, so a
`templates/` folder in any other repository is walked like every other folder.

Project-setup convergence is not a publication phase; it is contracted in
`local/projects/teleclaude/spec/feature/reconciliation/project-plumbing-convergence`.

The behavioral contract for this gating lives in
`local/projects/teleclaude/spec/feature/config/project-capability-manifest` — `UC-CFG-CAP-17` (an unsubscribed
`docs` capability leaves the snippet pipeline idle) and `UC-CFG-CAP-18` (an unsubscribed `agents`
capability leaves artifact distribution idle). Those scenarios are the single inventory for this
behavior; this spec references them rather than restating them.

### Use cases

#### UC-SPO23: Publication reads committed source

```gherkin
Given a recorded canonical commit whose changed paths owe publication
And another registered repository has a newer committed or uncommitted source state that has not run its own publication action
When the internal publication action runs for that recorded range
Then the triggering repository's homes advance to the committed main tip
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

#### UC-SPO24: Uncommitted source cannot publish

```gherkin
Given a home whose working tree holds uncommitted edits
When maintenance or telec sync publishes that home
Then the deployed output reflects only its committed files
And telec sync states that uncommitted changes were not published
```

#### UC-SPO25: Recovery converges to the committed main tip

```gherkin
Given publication failed for a recorded commit range
And later canonical-main commits exist
When an agent replays the publication action for the failed range
Then the homes the range touched are published at the committed main tip
And an agent retrieving the deployed documentation reads the main tip's committed input
And no uncommitted edit reaches the deployed output
```

#### UC-SPO28: An older replay never rolls a home back

```gherkin
Given a home already published at the committed main tip
When an agent replays the publication action for an older recorded range
Then that home's deployed documentation, commands, and skills still reflect the main tip
And an agent's local documentation retrieval still lists the main tip's catalog
And the replayed action completes without awaiting further recovery
```

#### UC-SPO26: telec sync publishes the invocation home and its nested homes

```gherkin
Given a member, an admin, or a non-worker agent in a directory of the canonical checkout on main that holds a teleclaude.yml
And the committed tree holds further homes beneath that directory
When it invokes telec sync
Then that home and every nested home in the committed tree are published from the committed main tip
And a gitignored folder or a foreign repository holding a teleclaude.yml is not published
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
Then that tier's docs/global is composed into the published snapshot exactly as a registered publisher's global tree is
And that tier's docs/local is cataloged in the tier's home and never composed into the snapshot
And no global agent-artifact publication path opens from the tier's home
```

#### UC-SPO21: A commit under a participating tier's home republishes the snapshot

```
Given the platform home carries TeleClaude's post-commit maintenance
And a person's or company's documentation home inside it participates in the documentation surface
When a documentation source under either half of that home is committed
Then the commit-boundary maintenance rebuilds that home's catalogs from the recorded commit and republishes the deployed documentation snapshot
And the tier's committed docs/global material is in that snapshot, exactly as a registered publisher's would be
And the tier's committed docs/local material is served from the home's local catalog and is absent from the snapshot
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

#### UC-SPO34: Installed publication uses the selected commit

```gherkin
Given an operator's machine on which no project checkout of the platform is registered
And its installation has just installed a release
When the install act publishes the platform's documentation and agent artifacts
Then the deployed documentation and agent artifacts are those committed at the installed release
And the install act is told whether publication completed, was already current, or was skipped with its build error
```

#### UC-SPO38: An install leaves the platform checkout's documentation in place

```gherkin
Given an operator's machine on which the platform's project checkout is registered
And that checkout's committed main tip is published
When its installation installs a release from another commit
Then the deployed documentation and agent artifacts remain those of the checkout's committed main tip
And the install act is told that the checkout publishes them
```

#### UC-SPO29: telec sync refuses outside a home

```gherkin
Given a directory that holds no teleclaude.yml, including a subfolder of a home
When telec sync is invoked there
Then it refuses and states that it runs only from a directory holding a teleclaude.yml
And no index build, distribution, or runtime-output write starts
```

#### UC-SPO30: A home whose build fails is skipped with its evidence

```gherkin
Given the global home and its nested homes are in scope
And one nested home's build fails
When telec sync runs in the global home
Then every other home publishes
And the failed home keeps its previous deployment
And the failed home is reported with its build error and the lint findings over its committed files
And telec sync exits non-zero
```

#### UC-SPO31: Syncing one home leaves the others untouched

```gherkin
Given a person home inside the global home
When telec sync runs in that person home
Then only that home's deployed documentation and entrypoints change
And every other home's deployed output is unchanged
```

#### UC-SPO32: Committed findings never block publication

```gherkin
Given a nested home whose committed files carry lint findings and still build
When maintenance or telec sync publishes its repository
Then that home publishes as committed
And no other home's publication waits on it
```

#### UC-SPO33: A home removed from the committed tree leaves deployment

```gherkin
Given a person home whose documentation is deployed
And a commit removes that home from the global home's committed tree
When maintenance or telec sync publishes the global home
Then that home's documentation and catalog entries are absent from the deployed output
And every other home's deployed output is unchanged
```

#### UC-SPO35: One publication shares one successfully read publisher inventory

Per-operation state ownership follows `sdlc/policy/code-quality-practices`.

```gherkin
Given a publication has successfully read the available registered-project inventory
When its later composition phases need that inventory
Then they reuse the same ordered project roots selected by that read's tier and availability checks
And the inventory is discarded when publication completes or fails
And the next publication reads current registry facts
And a missing registry or a failed read is not retained for reuse
```

#### UC-SPO36: A full-root rebuild recovers unavailable legacy history

```gherkin
Given the platform home's matching completed legacy generation identifiers name a missing historical commit object
When telec sync rebuilds the platform home and its nested homes from committed main
Then every successfully published home records that actual committed tip
And the legacy identifiers and historical read failure remain in the recovery evidence
And complete root reconciliation retires the legacy state
And removed homes are reconciled using current committed inventory and deployed ownership
And other publishers keep their activated revisions
```

#### UC-SPO37: Partial recovery preserves unresolved provenance

```gherkin
Given the platform home's completed legacy publication commit object is missing
And one current home's rebuild fails
When a full-root rebuild publishes the remaining homes
Then successful homes record their actual committed source
And the failed home retains its previous deployment without a fabricated generation
And the rebuild exits nonzero and retains unresolved legacy provenance
And a later Mother refresh refreshes proven homes and still reports unresolved history
When a later full-root rebuild publishes every current home successfully
Then the legacy state is retired and refresh uses the proven per-home generations
```

### Cross-context references

- **workflow / integration** — own todo delivery state and delivery-time
  `delivered_by` reconciliation.
- **config** — supplies project root and Mother-project resolution consumed by
  the distribution step, and the homes a committed tree holds with each path's
  owning home.
- **agent_runtime** — phase 3's distribution step deploys to the agent runtime
  boundary.

## Known caveats

- Publication is idempotent at the authored-source layer: it builds indexes
  from the committed snapshot and places published domain bundles inside the
  deployed generation. It writes gitignored `index.yaml` files with canonical
  checkout paths whenever a home publishes. The host
  documentation lease covers the checkout write and every publication action,
  including maintenance from a person's direct Git commit or merge and
  `telec sync`, so a later publication runs after an earlier one releases it.
  Publication never mutates authored source snippets or uses uncommitted files.

- Deployed artifacts reflect committed state. Between a save and its commit, the
  deployed tree is the previous commit's.

- Project bootstrap converges declarations, filters, and hooks but publishes no
  working-tree source. The first canonical commit activates the project's
  subscribed outputs; `telec sync` in the project's home publishes its committed
  state at any time.
- Commit-boundary maintenance owes publication only for the paths its
  repository's maintenance bindings name, and those bindings are anchored at the
  repository root.
- Publication fails explicitly when its distribution implementation is
  unavailable; publication never reports success after omitting a
  runtime-output phase.

- On a machine with an installation, commit-boundary publication runs the
  active release's code, which may be older than the committed source it
  publishes. A home whose committed source only newer publication code can
  build is skipped with its build error, and stays at its previous deployment
  until a release carrying that code is installed and the checkout publishes
  again — on its next activation that owes publication, or through `telec sync`.
