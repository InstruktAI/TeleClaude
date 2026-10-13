---
description: Release-channel installations select an admitted tag in detached HEAD
  and continue updating and maintaining that exact installed source.
visibility: public
---

# Release Checkout — Spec

## What it is

A beta or stable installation runs the exact source admitted by its release
channel. Its installed checkout has a detached HEAD at the selected release's
commit. The selected tag and full commit identity remain observable together.
Alpha retains its mainline checkout behavior.

Channel admission belongs to
`local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`.
This contract owns the installed checkout's source selection and posture; source
preservation follows `sdlc/policy/version-control-safety`.

## Canonical fields

### Installation identity

Reconciliation identifies the installed checkout from the executable target
published by installation. A caller's current directory, imported module
location, release channel or detached HEAD alone supplies no installation
identity. Maintenance and publication consume that installation identity rather
than deriving their own copies of it.

### Selected release

Detached HEAD refers directly to the immutable source selected under the
channel-update contract. The selected tag and full commit are retained together
as the checkout's release identity. Exact-source selection, release ordering and
activation replay remain governed by that contract and
`local/projects/teleclaude/design/architecture/deployment-pipeline`.

An ordinary argument-less Git pull in the installed release checkout cannot
advance its selected source onto the development branch. Release activation
selects subsequent source through channel admission.

Existing branches, unpublished commits and uncommitted work are preserved. A
source transition that cannot preserve them refuses with a concrete recovery
condition. Selecting older source requires the supported data transition named
by the channel-update contract; detachment supplies no rollback of persisted
state.

### Activation and maintenance

The installed release checkout remains eligible for its admitted release events,
installation, migrations, dependency reconciliation, documentation and artifact
publication, restart, and recorded maintenance replay. Those effects use the
installed activation's exact source, including when a local main branch names a
different commit. Their ordering, failure records and completion evidence remain
owned by the existing maintenance and channel-update contracts.

This eligibility identifies the installed checkout. It does not make an ordinary
detached development checkout or a slug worktree an installation. Development
and unrelated projects retain their existing maintenance eligibility.

Configuration migration preserves the installed project declaration under
`local/projects/teleclaude/spec/feature/config/document-migration`. Installation
and maintenance do not create commits in the selected release source.

### Use cases

#### UC-RC1: An admitted release is visibly selected

```gherkin
Given an operator's beta or stable installation has selected an admitted release
When the operator inspects the installed checkout
Then its HEAD is detached
And its selected release tag and full commit identity are observable together
```

#### UC-RC2: An ordinary pull cannot advance the release installation

```gherkin
Given an operator's installed release checkout selects a published tag
And the upstream development branch contains newer commits
When the operator invokes Git pull without a repository or branch argument
Then Git refuses branch integration
And the installed checkout still selects the same release commit
```

#### UC-RC3: A detached installation adopts its next admitted release

```gherkin
Given an operator's installation runs a release from detached HEAD
When a newer published release is admitted by its channel
And the channel-owned activation completes
Then the installed checkout remains in detached HEAD
```

Installed publication behavior is owned by UC-SPO34 in
`local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`.

#### UC-RC5: Conflicting local work survives a refused transition

```gherkin
Given an operator's installed checkout contains work that the selected transition cannot preserve
When the installation attempts that release activation
Then activation reports the unmet condition without claiming success
And the local work and its branch history remain available
```

#### UC-RC6: A detached development checkout gains no installation effects

```gherkin
Given an agent works in a detached checkout that is not the installed runtime checkout
When its repository receives a release event or performs local maintenance
Then detachment alone does not authorize installed-runtime activation there
```

## Known caveats

- Detached HEAD alone does not determine argument-less pull behavior: Git can
  select a configured fetch ref in a single-branch clone. The installed
  checkout's Git configuration participates in UC-RC2's refusal guarantee. An
  operator can still deliberately select or modify source through explicit Git
  operations.
- A selected commit identifies repository source, not the outcome of migrations,
  publication or daemon startup. Healthy activation still requires the evidence
  owned by the channel-update contract.
- Development-companion provisioning and compatibility-series enrollment have
  their own contracts; release selection creates neither a development clone nor
  a new enrollment policy.

## See Also

- docs/local/spec/feature/reconciliation/channel-gated-self-update.md
- docs/local/spec/feature/integration/event-bound-maintenance.md
- docs/local/spec/feature/integration/post-commit-maintenance.md
- docs/local/spec/feature/context/sync-pipeline-orchestration.md
