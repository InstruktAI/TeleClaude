---
description: The DeepSeek Harness runtime, its TUI and every installed plugin move together to the newest mutually compatible set, verified by exercising it and restored from a snapshot when verification fails — never by pinning, never by dropping a plugin.
visibility: internal
delivered_by:
  - dsh-compatible-upgrade
---

# DeepSeek Stack Convergence — Spec

## What it is

The DeepSeek Harness stack on a machine is the global `dsh` runtime plus, in
every runtime profile, the TUI package and each installed plugin. Each of those
packages publishes narrow compatibility requirements against the runtime and
the libraries it bundles, and the vendor publishes fixes frequently. Converging
the stack is one operation: it chooses the newest set in which everything that
is installed still fits, applies it, proves it by running it, and restores the
machine's previous state when the proof fails.

The operation never pins versions; each run chooses again from what is
published. It never removes a plugin to make a newer runtime fit, never accepts
a vendor compatibility exemption on the operator's behalf, and never leaves the
machine between two states: the result is the adopted set, verified, or the
previous set, restored.

An operator or an agent runs it on demand through the repository's sanctioned
make surface, and installation reaches the runtime only through it.

## Canonical fields

- **Stack.** The installed runtime version and, per profile, the TUI package
  and every installed plugin. A plugin installed from a local checkout belongs
  to the stack and is judged from its own manifest.
- **Required plugins.** The plugins TeleClaude's installation requires every
  profile to hold: its own hook plugin, from the local checkout of its plugins
  repository, and the checkpoint plugin, from the registry. They constrain the
  adopted set on every machine, including one where no profile holds them yet.
  A profile missing one gains it only as part of an adopted set, fitted like
  every installed package.
- **Candidate runtime.** Any published runtime release no older than the
  installed one, whatever release channel publishes it. The installed runtime
  is always a candidate, so staying put is always available.
- **Fit.** A package version fits a candidate runtime when every requirement
  it declares on the runtime — on the runtime's own packages, as peer
  requirements or as its declared runtime engine — holds for the candidate's
  version under strict semantic-version matching. A prerelease satisfies a
  requirement only where that requirement names a prerelease of the same
  major, minor and patch version. Every fitting set therefore also passes the
  runtime's own startup check, which admits prereleases more broadly.
- **Library advisory.** A requirement a package declares on a library the
  runtime bundles is judged against the version the candidate brings and
  reported when it does not hold, but it does not decide fit; the
  verification gate decides whether such a set works.
- **Adopted set.** The newest candidate runtime for which every package in
  every profile, and every required plugin, fits: a registry package through
  some published version, a local-checkout plugin through the manifest it
  already has. The set carries the newest fitting published version of each
  registry package. A candidate that leaves any of them without a fit is
  rejected, never adopted by dropping that package.
- **Plugin reference.** Every profile that holds a given registry plugin
  references it through the same registry requirement. A plugin from a local
  checkout keeps its local reference.
- **Snapshot.** Taken before the first change: the installed runtime version
  and every profile's manifest and lock state.
- **Launch profile.** The profile TeleClaude launches every DeepSeek session
  with, which holds the TUI.

<!-- planned:deepseek-launch-profile-convergence -->

- **Launch profile creation.** When the harness has no launch profile, the
  adopted set also creates it, holding the TUI and every required plugin. The
  TUI then counts among the packages that must fit, so a candidate without a
  fitting TUI version is rejected like any other. Creating the launch profile
  is a change in its own right: a run whose runtime and packages are already
  the newest that fit still adopts the set that creates it. A run that
  restores its snapshot also removes the launch profile it created, and the
  report of a run that keeps it says the launch profile was created. A launch
  profile that already exists is converged like every other profile and is
  never recreated or reset, and no other profile is ever created.

<!-- /planned:deepseek-launch-profile-convergence -->

- **Verification gate.** An adopted set is kept only when, run from a
  throwaway working directory, every profile starts with no startup diagnostic
  and a composed configuration; the launch profile reaches its ready composer
  without the first-run guide; and, in the launch profile, a prompt completes a
  turn without a turn error and a turn completes while a hook returns
  additional context.
- **Run in progress.** Another convergence holds the stack. A run changes
  nothing while another run is in progress. Running DeepSeek sessions are not
  inspected: the runtime and profile packages are replaced in place.
- **Outcome.** Exactly one of: upgraded, unchanged, rolled back, or rollback
  incomplete. The report names the outcome and the evidence behind it,
  including every library advisory of the adopted set; an unchanged outcome
  names whether no newer set fits or another run was in progress.

### Use cases

#### UC-DSC1: The newest mutually compatible set is adopted

```gherkin
Given a runtime release newer than the installed one exists
And every package installed in every profile fits it
When an operator runs the DeepSeek stack convergence
Then the runtime moves to the newest such release
And each profile's TUI and registry plugins move to their newest published versions that fit it
And the operator's report lists each package's previous and adopted version
```

#### UC-DSC2: A runtime release that would cost a plugin is passed over

```gherkin
Given the newest candidate runtime leaves an installed plugin without a fit
And an older candidate, still newer than the installed runtime, keeps every installed package fitting
When an operator runs the DeepSeek stack convergence
Then the runtime moves to that older candidate
And every plugin installed before the run is still installed in every profile that held it
```

#### UC-DSC3: With no consistent newer set the machine stays put and says why

```gherkin
Given no candidate runtime, the installed one included, keeps every installed package and every required plugin fitting, or the newest set that fits is already installed
When an operator runs the DeepSeek stack convergence
Then the runtime, every profile manifest and every profile's lock state are unchanged
And the operator's report names each blocking package, the requirement it declares, and the version that fails it
```

#### UC-DSC4: A compatibility exemption is never granted on the operator's behalf

```gherkin
Given a plugin could load with a candidate runtime only under a vendor compatibility exemption
When the DeepSeek stack convergence runs
Then no exemption is granted
And that plugin counts as not fitting that candidate
```

#### UC-DSC5: Profiles converge on one reference per plugin

```gherkin
Given two profiles hold the same registry plugin through different references
When the DeepSeek stack convergence adopts a set
Then both profiles reference that plugin through the same registry requirement
And a plugin installed from a local checkout keeps its local reference
```

#### UC-DSC6: A verified set is kept

```gherkin
Given the DeepSeek stack convergence has applied an adopted set
When every check of the verification gate passes
Then the adopted set remains installed
And the operator's report states the outcome as upgraded
```

#### UC-DSC7: A failed apply or a failed check restores the snapshot

```gherkin
Given the DeepSeek stack convergence has taken its snapshot and begun changing the machine
When applying the adopted set fails, or any check of the verification gate fails
Then the runtime version, every profile manifest and every profile's lock state are restored from the snapshot
And every profile starts as it did before the run
And the operator's report states the outcome as rolled back and names the failed step or check
```

#### UC-DSC8: A restore that cannot complete is reported as such

```gherkin
Given the DeepSeek stack convergence is restoring its snapshot
When part of the restore fails
Then the operator's report states the outcome as rollback incomplete
And names every part of the stack that differs from the snapshot
```

#### UC-DSC9: Verification leaves nothing behind

```gherkin
Given the verification gate has run, whether it passed or failed
When the DeepSeek stack convergence finishes
Then no working directory, process or runtime session the gate started remains
And no session started by the gate's turns appears in the operator's session list or history
```

#### UC-DSC10: Installation reaches the runtime only through convergence

```gherkin
Given DeepSeek is enabled as an agent runtime
When an operator runs the installer
Then the runtime is installed or moved only through the DeepSeek stack convergence
And after the installer finishes every profile still holds the set convergence left in place
And an unchanged or rolled-back outcome is shown to the operator without failing the rest of the installation
```

#### UC-DSC11: An unpublished local plugin is judged by its own manifest

```gherkin
Given a profile holds a plugin installed from a local checkout that has no published version
And its manifest's compatibility requirements hold for a newer candidate runtime
And every other installed package fits that candidate
When an operator runs the DeepSeek stack convergence
Then the runtime moves to that candidate
And the local plugin stays installed through its local reference
```

#### UC-DSC12: A profile missing a required plugin gains it within the adopted set

```gherkin
Given a profile does not hold one of the required plugins
When the DeepSeek stack convergence adopts a set in which that plugin fits
Then the profile holds the plugin after the run, at its fitting version or through its local reference
```

#### UC-DSC13: A run changes nothing while another run is in progress

```gherkin
Given another DeepSeek stack convergence is in progress
When an operator or the installer runs the DeepSeek stack convergence
Then the runtime, every profile manifest and every profile's lock state are unchanged
And the operator's report states the outcome as unchanged because another run was in progress
```

#### UC-DSC14: Newer plugin releases are adopted on the installed runtime

```gherkin
Given the installed runtime is the newest candidate for which every package and required plugin fits
And a newer published version of the TUI or of an installed plugin fits it
When an operator runs the DeepSeek stack convergence
Then the runtime stays at the installed release
And each profile moves to the newest fitting version of that package
And the set is verified, and restored on failure, like any adopted set
```

<!-- planned:deepseek-launch-profile-convergence -->

#### UC-DSC15: A missing launch profile is created within the adopted set

```gherkin
Given the launch profile does not exist
And a candidate runtime exists at which the TUI, every required plugin and every installed package fit
When an operator or the installer runs the DeepSeek stack convergence
Then the launch profile holds the TUI and every required plugin, at their fitting versions or through their local references
And the verification gate's checks have passed in it
And no other profile is created
And the operator's report states the outcome as upgraded and says the launch profile was created
```

#### UC-DSC16: A machine that has never run DeepSeek becomes startable through installation

```gherkin
Given DeepSeek is enabled as an agent runtime
And the machine has neither the DeepSeek runtime nor its launch profile
And the operator's DeepSeek account credentials are usable
And a candidate runtime exists at which the TUI and every required plugin fit
When an operator runs the installer
And the set that creates the launch profile passes the verification gate
Then the runtime is installed and the launch profile created through the DeepSeek stack convergence
And TeleClaude can start a DeepSeek session in the launch profile with no manual setup
```

#### UC-DSC17: The launch profile is created even when nothing else would move

```gherkin
Given the launch profile does not exist
And the installed runtime and every installed package are already the newest that fit
When an operator runs the DeepSeek stack convergence
Then the runtime stays at the installed release
And the launch profile is created within an adopted set, verified and restored on failure like any other
```

#### UC-DSC18: A creation that does not survive leaves no launch profile behind

```gherkin
Given the launch profile does not exist
When the DeepSeek stack convergence finds no candidate at which the TUI and every required plugin fit, or applying or verifying the set that creates the launch profile fails and the restore completes
Then no launch profile exists after the run
And the runtime and every other profile are as they were before the run
And the operator's report names the blocking package, or the failed step or check
```

#### UC-DSC20: A created launch profile that cannot be removed is reported

```gherkin
Given the DeepSeek stack convergence created the launch profile and is restoring its snapshot
When removing the created launch profile fails
Then the operator's report states the outcome as rollback incomplete
And names the launch profile among the parts of the stack that differ from the snapshot
```

#### UC-DSC19: An existing launch profile is never recreated or reset

```gherkin
Given the launch profile exists
When the DeepSeek stack convergence runs
Then the launch profile is not recreated, reset or replaced
And it changes only as the convergence changes every existing profile
```

<!-- /planned:deepseek-launch-profile-convergence -->

## Known caveats

- Declared compatibility is necessary but not sufficient: a plugin can satisfy
  every requirement and still fail in use, so only the verification gate's
  turns establish that an adopted set works.
- The gate's turns run against the live DeepSeek account and need usable
  authentication; when they cannot run, the gate fails and the snapshot is
  restored.

<!-- planned:deepseek-launch-profile-convergence -->

- A launch profile the convergence creates carries none of the operator's own
  preferences for the profile; those are theirs to add. TeleClaude passes its
  own model choice with every launch rather than through the profile.

<!-- /planned:deepseek-launch-profile-convergence -->

## See Also

- docs/local/adr/0112-deepseek-fit-judges-runtime-requirements-only.md — why fit judges only runtime requirements and library requirements are advisories.
