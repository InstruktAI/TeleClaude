---
description: Release-channel installations select an admitted tag in detached HEAD
  and continue updating and maintaining that exact installed source.
visibility: public
---

# Release Checkout — Spec

## What it is

An installation runs the exact source of its active release, whatever its
channel. Each release is a worktree of the installation's kept repository with
a detached HEAD at the selected revision's commit. For a published release, the
selected tag and full commit identity remain observable together; a mainline
revision installed on the alpha channel is identified by its full commit.

Channel admission belongs to
`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`,
and the releases, the install act and rollback to
`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`.
This contract owns a release's source selection and posture.

## Canonical fields

### Installation identity

Reconciliation identifies the installation from its own location and its
active-release pointer; the active release is the one the pointer names. A
caller's current directory, imported module location, release channel,
detached HEAD or the target of the published `telec` alone supplies no
installation identity, and no project checkout is ever an installation. The
install act and publication consume that installation identity rather than
deriving their own copies of it.

### Selected release

A release's detached HEAD refers directly to the immutable source selected for
it. For a published release, the selected tag and full commit are retained
together as the release identity. Exact-source selection and release ordering
remain governed by the channel-update contract and
`local/projects/teleclaude/design/architecture/deployment-pipeline`.

An ordinary argument-less Git pull in a release cannot advance its selected
source onto the development branch. A later revision becomes a new release
through the install act; an installed release's source never moves.

Nothing develops or commits in a release, so a release holds no branches,
unpublished commits or uncommitted work of its own. Detachment supplies no
rollback of persisted state.

### Activation and maintenance

A release's migrations, environment build, documentation and artifact
publication and the daemon's replacement are performed by the install act that
makes it active, from that release's exact source, whatever any project's local
main branch names. Their ordering, failure records and completion evidence are
owned by `local/projects/teleclaude/spec/feature/reconciliation/installed-releases`.

Only a release of the installation is installed source. A detached development
checkout, a slug worktree or a project checkout on any branch gains no
installation effects from its posture.

Configuration migration preserves the declarations it migrates under
`local/projects/teleclaude/spec/feature/config/document-migration`. The install
act creates no commits in a release.

### Use cases

#### UC-RC1: An admitted release is visibly selected

```gherkin
Given an operator's installation has installed a published release
When the operator inspects the active release
Then its HEAD is detached
And its selected release tag and full commit identity are observable together
```

#### UC-RC2: An ordinary pull cannot advance the release installation

```gherkin
Given an operator's active release selects a published tag
And the upstream development branch contains newer commits
When the operator invokes Git pull without a repository or branch argument in that release
Then Git refuses branch integration
And the release still selects the same commit
```

#### UC-RC3: A detached installation adopts its next admitted release

```gherkin
Given an operator's installation runs a release from detached HEAD
When a newer published release is admitted by its channel
And the install of that release completes
Then the new active release is in detached HEAD at the admitted release's commit
```

Installed publication behavior is owned by UC-SPO34 in
`local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`.

#### UC-RC5: Conflicting local work survives a refused transition

#### UC-RC6: A detached development checkout gains no installation effects

```gherkin
Given an agent works in a detached checkout that is not a release of the installation
When its repository receives a release event or performs local maintenance
Then detachment alone does not authorize installed-runtime activation there
```

<!-- planned:queued-release-events-strand-superseded-posture-action -->

#### UC-RC7: A superseded release's owed posture settles without moving source

```gherkin
Given an operator's installation owes posture normalization for an admitted release
And a later admitted release descending from it is selected before that normalization runs
When the owed normalization for the earlier release runs or is replayed
Then it completes without selecting the earlier release's source
And the installed checkout still selects the later release in detached HEAD
```

<!-- /planned:queued-release-events-strand-superseded-posture-action -->

## Known caveats

- Detached HEAD alone does not determine argument-less pull behavior: Git can
  select a configured fetch ref in a single-branch clone. The installed
  checkout's Git configuration participates in UC-RC2's refusal guarantee. An
  operator can still deliberately select or modify source through explicit Git
  operations.
- A selected commit identifies repository source, not the outcome of migrations,
  publication or daemon startup. Healthy activation still requires the evidence
  owned by the channel-update contract.
- Compatibility-series enrollment has its own contract; release selection
  creates no development clone and no new enrollment policy.

## See Also

- docs/local/spec/feature/reconciliation/channel-gated-self-update.md
- docs/local/spec/feature/integration/event-bound-maintenance.md
- docs/local/spec/feature/integration/post-commit-maintenance.md
- docs/local/spec/feature/context/sync-pipeline-orchestration.md
