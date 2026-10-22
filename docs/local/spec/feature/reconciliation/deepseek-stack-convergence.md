---
description: The DeepSeek Harness runtime, its TUI and every installed plugin move
  together to the newest mutually compatible set, verified by exercising it and restored
  from a snapshot when verification fails — never by pinning, never by dropping a
  plugin.
visibility: internal
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

- **Verification gate.** An adopted set is kept only when, run from a
  throwaway working directory, every profile starts with no startup diagnostic
  and a composed configuration; the launch profile reaches its ready composer
  without the first-run guide; and, in the launch profile, a prompt completes a
  turn without a turn error and a turn completes while a hook returns
  additional context.
  The gate uses a temporary user home and working directory. It removes them,
  stops its terminal server and terminates every process it starts after either
  a passing or failing check; its test sessions do not appear in the operator's
  session list or history.
- **Run in progress.** Another convergence holds the stack. A run changes
  nothing while another run is in progress. Running DeepSeek sessions are not
  inspected: the runtime and profile packages are replaced in place.
- **Outcome.** Exactly one of: upgraded, unchanged, rolled back, or rollback
  incomplete. The report names the outcome and the evidence behind it,
  including every library advisory of the adopted set; an unchanged outcome
  names whether no newer set fits or another run was in progress. When no newer
  set fits, it lists each blocking package, its declared requirement and the
  version that fails it. Apply or verification failure restores the runtime and
  every profile's manifest and lock state from the snapshot, and the report
  names the failed step or check. A rollback-incomplete report lists every part
  of the stack that still differs from the snapshot.

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

#### UC-DSC3: With no consistent newer set the machine stays put and says why

#### UC-DSC4: A compatibility exemption is never granted on the operator's behalf

#### UC-DSC5: Profiles converge on one reference per plugin

#### UC-DSC6: A verified set is kept

#### UC-DSC7: A failed apply or a failed check restores the snapshot

#### UC-DSC8: A restore that cannot complete is reported as such

#### UC-DSC9: An operator can verify the stack without leaving sessions behind

```gherkin
Given an operator runs the DeepSeek stack convergence
When its verification passes or fails
Then no process or runtime session started by verification remains
And no verification session appears in the operator's session list or history
```

#### UC-DSC10: An operator can finish installation when DeepSeek cannot advance

```gherkin
Given an operator installs TeleClaude with DeepSeek enabled
When DeepSeek stack convergence reports unchanged or rolled back
Then the installation finishes and shows that outcome to the operator
```

#### UC-DSC11: A local plugin remains installed during a runtime update

```gherkin
Given an operator has a locally installed plugin compatible with a newer DeepSeek runtime
When they run stack convergence
Then the runtime updates and the local plugin remains installed
```

#### UC-DSC12: A profile missing a required plugin gains it within the adopted set

#### UC-DSC13: A run changes nothing while another run is in progress

#### UC-DSC14: An operator can update plugins without changing the runtime

```gherkin
Given an operator has a newer TUI or plugin version compatible with the installed DeepSeek runtime
When they run stack convergence
Then the compatible package updates while the runtime stays at its installed release
And the resulting stack is verified and restored on failure
```

#### UC-DSC15: An operator can prepare a missing DeepSeek launch profile

```gherkin
Given an operator has an installed DeepSeek runtime without its launch profile
And the required plugins and TUI fit that runtime
When they run stack convergence
Then the launch profile is created and passes the readiness checks
And the operator is told that the profile was created
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

#### UC-DSC18: A creation that does not survive leaves no launch profile behind

#### UC-DSC20: A created launch profile that cannot be removed is reported

#### UC-DSC19: An existing launch profile is never recreated or reset

## Known caveats

- Declared compatibility is necessary but not sufficient: a plugin can satisfy
  every requirement and still fail in use, so only the verification gate's
  turns establish that an adopted set works.
- The gate's turns run against the live DeepSeek account and need usable
  authentication; when they cannot run, the gate fails and the snapshot is
  restored.

- A launch profile the convergence creates carries none of the operator's own
  preferences for the profile; those are theirs to add. TeleClaude passes its
  own model choice with every launch rather than through the profile.

## See Also

- docs/local/adr/0112-deepseek-fit-judges-runtime-requirements-only.md — why fit judges only runtime requirements and library requirements are advisories.
