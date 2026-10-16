---
description: Installation eagerly provisions and retains a sibling development checkout for a release-channel installation, independently of the running release.
delivered_by:
  - release-development-checkouts
---

# Development Checkout — Spec

## What it is

A beta or stable installation has a persistent development clone beside its
installed checkout. Installation establishes this working resource before
reporting development readiness. The operator sees its location and its purpose:
autonomous diagnosis, fixes, and contribution while the installed release keeps
serving. Alpha retains development and immediate activation in its existing
checkout.

The development clone is a sibling whose directory name appends `-dev` to the
installed checkout's name. It has its own Git object store, upstream remote and
development environment. Its todo and integration worktrees belong to it.
This is retained project work, including unpublished commits and uncommitted
files, under `sdlc/policy/version-control-safety`.

## Canonical fields

### Provisioning and lifetime

The full installation operation provisions the companion eagerly. A successful
run leaves a usable, registered development checkout; an unsuccessful run names
the failed provisioning step and preserves the running installation and any
existing development work. An existing directory is reused only when its
repository and recorded checkout association identify the expected companion.
A conflicting directory is left untouched and reported.

Repeating installation reuses the association and checkout. Release adoption,
session closure and an empty work queue retain the clone and its worktrees.
Changing channel preserves existing work and the association; it creates no
second companion. Explicit retirement accounts for live worktrees, claims and
unpublished work before releasing the resource. Project cleanup and backup
classification treat it as retained development state rather than a cache.

Registration uses config's association operation
after its installation registration request has succeeded
(`local/projects/teleclaude/spec/feature/config/project-registry`). A provisioning
receipt records progress through clone creation, environment preparation and
registration, so retry converges on the same resource after an interruption.
The companion's own dependency installation is development preparation; it
performs no host-service or installed-runtime provisioning. Checkout purpose
comes from the association, never from a directory-name guess.

### Development participation

Provisioning a development resource starts no agent work on its own. Existing
workflow dispatch policy governs local work, and source delivery retains the
supported upstream-mainline contract. Workspace readiness supplies no public
contribution handler or publishing authorization.

<!-- planned:reviewed-pr-contributions -->

### Installation and contribution

Publishing a contribution follows the operator's standing contribution
enrollment under
`local/projects/teleclaude/spec/feature/workflow/contribution-export`.
Installation explains both the local workspace and whether public contribution
is enabled; unattended runs consume the same declared choice without prompting
(`local/projects/teleclaude/spec/feature/reconciliation/fresh-machine-bootstrap`).
Public contribution becomes selectable with the export/adoption capability;
missing capability is reported while the existing development workspace remains
available.
<!-- /planned:reviewed-pr-contributions -->

### Use cases

#### UC-DC1: Installation establishes the development workspace eagerly

```gherkin
Given an operator installs a beta or stable installation
When full installation succeeds
Then the operator is shown a usable sibling development checkout and its purpose
And that checkout already exists before any bug-fixing session starts
```

#### UC-DC2: Reinstallation preserves development work

```gherkin
Given an operator's installation already has its development checkout
And that checkout holds active worktrees and unpublished work
When installation runs again or an admitted release is installed
Then the same development checkout and its existing work remain available
And no additional companion checkout is created
```

#### UC-DC3: A conflicting destination is preserved

```gherkin
Given the predicted companion location holds a different repository or unrelated files
When an operator installs the platform
Then development provisioning reports the destination conflict
And the existing destination remains unchanged
And the installation does not claim development readiness
```

#### UC-DC4: Interrupted provisioning converges on its existing resource

```gherkin
Given development provisioning was interrupted after creating its clone
When the operator repeats installation
Then provisioning resumes for that clone
And a successful result identifies one usable companion
```

#### UC-DC5: Development preparation does not recursively provision the platform

```gherkin
Given an agent prepares dependencies in a registered development checkout
When preparation completes
Then the development environment is ready for that checkout
And no companion of the development checkout is created
And the installed platform's service configuration is unchanged
```

## Known caveats

- A retained path is not protection against deletion of its parent directory by
  an external operator. Recovery of unpublished work depends on the operator's
  retained-state backup, not on fetching the upstream repository again.
- The platform's own release is still the workflow controller. Source checkout
  selection alone supplies no newer daemon command or capability; cross-version
  consumers follow `local/projects/teleclaude/spec/feature/reconciliation/fleet-cross-version-interop`.
