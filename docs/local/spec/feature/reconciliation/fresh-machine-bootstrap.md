---
description: Installation takes a fresh machine to a startable, owned TeleClaude that
  serves its published documentation, with or without a person present — never blocking
  on input it was not given, never leaving the machine without an owner, and converging
  on every repeat run.
visibility: internal
---

# Fresh-Machine Bootstrap — Spec

## What it is

Installation is the only step a fresh machine needs before it can run TeleClaude.
When installation completes, the machine can be started with no further setup,
has an owner who can administer it, and serves the documentation and agent
artifacts of the checkout it was installed from.

Installation runs in one of two situations, and it reads which one from whether
it has a terminal:

- **A person at a terminal.** Installation may ask that person for what it
  needs, as it does today for its interactive choices.
- **No terminal.** Automation runs installation, for example a disposable
  machine being provisioned or a machine's own maintenance re-running its
  install. Nothing that installation needs may come from a person. It comes
  from inputs provisioned beforehand, or installation fails promptly and names
  the missing input and how to provide it. Installation never waits on a
  prompt or a dialog that nobody will answer.

Installation is repeatable. A second run over an installed machine changes
nothing that the first run already settled. It never duplicates, replaces or
promotes a person, and never overwrites environment settings an operator made.

The machine's owner is its first platform administrator. Installation
establishes that owner only while no person is registered, which is the one
moment no registered administrator exists who could add people through the
ordinary configuration surface. After that, people are added only through that
surface, under its clearance rules.

Signing the launcher apps is a separate boundary, owned by
`local/projects/teleclaude/spec/feature/reconciliation/launcher-code-identity`.
Full Disk Access is a separate capability again: installation never grants it,
and the machine's health report never depends on it.

## Canonical fields

- **Owner seed.** Installation's own input naming the machine's first
  platform administrator. It is given to installation without a terminal, for
  example through its environment or a seed file. It names one person.
- **Matching seed.** A seed whose person is already registered as a
  platform administrator.
- **Conflicting seed.** A seed given while people are already registered, whose
  person is not registered as a platform administrator. Acting on it would add
  an owner to an owned machine or promote someone.
- **Local defaults.** Environment settings that let the machine start using
  only the local services installation itself provisions.
- **Optional desktop applications.** Graphical applications installation can
  add for features the operator may want but the platform does not need to run,
  together with any background service that comes with them. Each is installed
  only by the operator's explicit choice. An application already present is not
  a choice made for its companion service.

### Use cases

#### UC-FMB1: An installation without a terminal never waits on a person

```gherkin
Given a fresh machine with the platform's documented prerequisites
And installation runs with no terminal
And the owner seed is provided
When installation runs
Then it completes without any prompt or dialog waiting for an answer
And every tool it installs for its own later steps is usable by those steps in the same run
```

#### UC-FMB2: A step that cannot proceed unattended fails promptly and says why

```gherkin
Given installation runs with no terminal
And a step needs input or a decision that was not provided
When installation reaches that step
Then it fails within a bounded time instead of waiting
And it names the step, the missing input and how to provide it
```

#### UC-FMB3: Optional desktop applications are installed only by choice

```gherkin
Given an optional desktop application, or its companion service, is absent from the machine
When installation runs with no terminal
Then the run adds neither of them
When an operator at a terminal runs installation and declines that application
Then the run adds neither of them
When an operator at a terminal runs installation and chooses that application
Then the run adds whichever of the application and its companion service is absent
And in every case, no optional application or companion service already present is removed
```

#### UC-FMB4: A machine without environment settings becomes startable

```gherkin
Given a machine whose checkout has no environment settings file
When installation completes
Then the checkout holds an environment settings file with local defaults
And the machine starts with no further setup step
And once started, the platform reports itself healthy
```

#### UC-FMB5: Existing environment settings are kept

```gherkin
Given a checkout whose environment settings file already exists
When installation runs
Then that file is unchanged
```

#### UC-FMB6: The owner seed establishes the first administrator

```gherkin
Given no person is registered
And installation is given an owner seed
When installation completes
Then exactly one person is registered: the seeded person, as platform administrator
And that person can administer the machine through the ordinary configuration surface
```

#### UC-FMB7: A matching seed changes nothing

```gherkin
Given the seeded person is already registered as platform administrator
When installation runs again with the same seed
Then the registered people are unchanged
And installation reports the owner as already present
```

#### UC-FMB8: A conflicting seed is reported and changes nothing

```gherkin
Given people are registered
And installation is given a seed whose person is not registered as platform administrator
When installation runs
Then the registered people are unchanged and nobody is added or promoted
And installation reports the mismatch, naming the seeded person and what the registry holds for them
And installation does not report success
```

#### UC-FMB9: An unowned machine without a terminal or a seed fails before claiming success

```gherkin
Given no person is registered
And installation runs with no terminal and no owner seed
When installation runs
Then it does not report success
And it names the missing owner seed and how to provide it
```

#### UC-FMB10: An operator at a terminal is asked for the first administrator

```gherkin
Given no person is registered
And an operator at a terminal runs installation without an owner seed
When installation needs the machine's owner
Then it asks the operator for the first administrator
And the person the operator gives is registered as platform administrator
```

#### UC-FMB11: An owned machine needs no seed

```gherkin
Given a platform administrator is registered
When installation runs with no terminal and no owner seed
Then owner establishment changes nothing and does not fail the installation
```

#### UC-FMB12: Installation publishes the checkout's committed documentation

```gherkin
Given a fresh machine whose home has never received published documentation
When installation completes
Then the home serves the documentation and agent artifacts committed at the installed commit
And a published snippet can be read through the documentation surface
And the platform starts without failing to find its published documentation
And uncommitted changes in the checkout are not published
```

#### UC-FMB13: Installation that cannot publish does not succeed

```gherkin
Given installation reaches publication of the installed checkout's documentation
When that documentation cannot be published
Then installation does not report success
And it names the cause publication reported
```

#### UC-FMB14: A release installed from a tag publishes that release

```gherkin
Given a machine whose home serves documentation from another commit
When installation runs from a checkout of a release tag
Then the home serves the documentation and agent artifacts committed at that release
```

#### UC-FMB15: Installation exposes time spent in its stages

Following `sdlc/policy/observability`:

```gherkin
Given installation runs in full, CI or dependency-only mode
And TELECLAUDE_LOG_LEVEL is DEBUG or TRACE
When an installation stage completes
Then the install log records one structured DEBUG completion with its name and elapsed seconds
And the default INFO level omits stage timing records
And stage ordering and existing failure handling are preserved
```

#### UC-FMB16: Repositories convergence left alone do not fail installation

```gherkin
Given an agent or a person runs installation, in full or dependency-only mode
And documentation layout convergence's result has some repository blocked or deferred and none failed
When installation completes
Then the agent or person reads a warning that repositories were left blocked or deferred, pointing at convergence's report
And installation reports success and its result is successful
```

#### UC-FMB17: A failed documentation layout convergence fails installation

```gherkin
Given an agent or a person runs installation, in full or dependency-only mode
And documentation layout convergence's result has a failed repository
When installation reaches its end
Then the agent or person reads that documentation layout convergence failed, pointing at convergence's report
And installation does not report success and its result is non-zero
```

### Cross-context references

- **config** — the person registry the owner seed is checked against and
  written to, the environment settings file, and its local defaults.
  Declarations only; installation adds no configuration rule.
- **identity** — what platform administrator standing grants. After the owner
  is established, adding people is cleared by
  `local/projects/teleclaude/spec/feature/identity/configuration-target-clearance`.
- **context** — the publication engine installation calls. Publication's
  own contract stays with
  `local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`.
- **reconciliation** — launcher signing, under
  `local/projects/teleclaude/spec/feature/reconciliation/launcher-code-identity`,
  and what installation records in the home's history, under
  `local/projects/teleclaude/spec/feature/reconciliation/home-repository`.

- **context** — documentation layout convergence and the classification of
  its result into settled, blocked or deferred, and failed, under
  `local/projects/teleclaude/spec/feature/context/documentation-layout-convergence`.
  Installation decides only how it completes on each class.

<!-- planned:release-development-checkouts -->

### Development readiness

Full installation composes the durable companion provisioning operation under
`local/projects/teleclaude/spec/feature/reconciliation/development-checkout`.
Dependency-only preparation in a registered development checkout stays in that
checkout's environment. Full installation reports the companion's result and
contribution enrollment along with runtime readiness; it claims completion only
when the required provisioning operations succeeded.
<!-- /planned:release-development-checkouts -->

## Known caveats

- The platform's documented prerequisites (the package manager, the developer
  command-line tools and the language runtimes installation builds on) are not
  provisioned by installation. A missing prerequisite fails installation and
  names it.
- An owner seed is trusted as given. Anyone able to run installation as the
  machine's operating-system user can already edit the person registry
  directly. The seed adds no capability that user lacks, and it acts only
  while no person is registered.
- A program with no terminal still cannot act as a registered person
  (`local/projects/teleclaude/spec/feature/identity/terminal-email-login`).
  Establishing the owner registers a person; it does not let unattended
  programs act as them.
