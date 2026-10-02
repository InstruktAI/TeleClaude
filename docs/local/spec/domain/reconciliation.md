---
visibility: internal
description: Frozen v1 ownership anchor for installation and fleet convergence behavior.
---

# Reconciliation Domain Spec — Spec

## What it is

The v1 reconciliation area compares declared installation capabilities with
observed machine state and drives the supported convergence paths. It is a
maintenance-only appliance surface, not the replacement reconciliation design.

## Canonical fields

- **Current behavior:** reconciliation feature specs and operational contracts
  that require this anchor.
- **Implementation roots:** `teleclaude/core/reconciliation/` and sanctioned
  installation/service-control surfaces.
- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. Replacement fleet design belongs to
  TeleClaudeNext.

### Ownership boundary

- **Owns:** comparison of declared installation capabilities with observed
  machine state and selection of sanctioned convergence actions, including the
  rule deciding which material the home's history retains; and each macOS
  machine's launcher code identity — its signing authority, the signing store
  that holds it, the unlock secret that opens that store, and the record of what
  the installed launchers were built from. That state is created on the machine
  it serves, is never shared with another machine, and lies outside the home's
  retained set.
- **Does not own:** service lifecycle mechanics, configuration schema, the
  application behavior of the capabilities it reconciles, or what a commit
  boundary does with a membership answer it is given.
- **Published contracts:** reconciliation observations, plans, and outcomes
  consumed by sanctioned installation and service-control surfaces; and a
  membership predicate returning, for any path, exactly one of `retained`,
  `not-retained`, or `outside` — the last where the path resolves beyond the home
  root. The predicate reports membership only; the consumer's response to a
  result is that consumer's own contract.
- **Also published:** fleet discovery facts for this installation — which node
  is the mesh master, and which capabilities this node advertises — carried on
  the heartbeat as additive fields and readable by every peer. The context owns
  the declaration and its advertisement only; which capability a consumer
  requires before coordinating, and what it does when a peer lacks it, is that
  consumer's own contract.

#### Launcher code identity

- **State.** Per macOS machine: the signing authority, selected by its
  fingerprint; the signing store that holds it; the unlock secret, generated on
  the machine and kept outside that store; and the built-from record — the
  digest of the launcher inputs together with the fingerprint of the authority
  that signed the installed launchers. All of it is machine-local, sits outside
  the home's retained set (the membership predicate answers `not-retained`),
  and is never imported from or exported to another machine.
- **Decision boundary (core).** One reconciliation core operation converges a
  machine's launcher code identity. It decides whether to create, reuse or
  refuse the authority; whether the launcher set must be rebuilt because its
  inputs, the installed set or the authority changed, or whether there is
  nothing to do; and whether a verified rebuilt set replaces the installed one.
  It confirms unattended readiness before signing and bounds every keychain and
  signing call with a timeout. A
  deliberate renewal is the same operation invoked with explicit renewal
  intent. Its published result names the authority it signed with, whether it
  created it, whether anything was rebuilt, the cause and remedy of a failure,
  and the launchers whose Full Disk Access is owed again.
- **Infrastructure.** Keychain operations, code-signing tool invocations, the
  launcher compile and the replacement of installed bundles execute behind
  ports the core operation drives; they decide nothing.
- **Signing-store discovery.** Before checking readiness for a signing run,
  the operation ensures the dedicated store is registered in the user's
  keychain search list. It appends the store only when absent, preserves every
  existing entry and its order, and never changes the default keychain. The
  registration persists; a run with nothing to rebuild leaves it untouched.
  The operation bounds registration with the same per-call deadline and
  reports a registration failure before signing. Unrelated keychain state
  stays outside the operation's scope (`sdlc/policy/security-awareness`).
- **Consumers.** The full installer, the manual launcher rebuild, the renewal
  door and the channel updater's install stage invoke the operation's entry
  point and act only on its result: a failure fails the invoking step under
  that step's own failure handling. Post-commit maintenance reaches it through
  the full installer. No consumer reads the store, the secret or the record.

<!-- planned:startable-unattended-install -->
#### Fresh-machine bootstrap

- **Decision boundary (core).** One reconciliation operation decides the
  machine's owner from the installation's owner seed, the person registry and
  whether the run has a terminal. With no person registered, a seed
  establishes its person as platform administrator, and a terminal operator
  without a seed is asked for one. A run with no terminal and no seed is
  refused. With people registered, a matching seed is a no-op, no seed needs
  nothing, and a conflicting seed is refused. A refusal writes nothing and fails
  the installation, naming the mismatch or the missing seed. The decision is
  taken before any long-running installation step, and its write happens after
  configuration is migrated and validated and before home activation.
- **Writes it delegates.** The owner's registration (the registry entry and the
  person's declaration) is made through config's person registration, never
  through the configuration surface. No caller holds clearance on an empty
  registry. The person home's template layer is left to home activation, which
  writes it over absent targets and records it as its own write. The
  registration itself stays outside installation's record, as every registration
  made through the configuration surface does.
- **Startable checkout.** When the checkout has no environment settings file,
  installation writes one through config's environment writer, holding only the
  local defaults for services installation itself provisions. An existing file
  is never rewritten.
- **Install-time publication.** After home activation, installation invokes
  context's publication routine for the installed checkout's home in owed mode,
  and acts only on its result. Publication's rules stay context's: it publishes
  the checkout's committed `main` tip, so a checkout without a local `main`
  publishes nothing. A run that publishes nothing or skips a home is reported
  with its cause and the recovery command, and does not fail the installation.
  The routine is not given the global home: that home's own publication
  follows its commits.
- **Unattended execution.** The installation's own tool directory is on its
  search path from the start of the run. In a run without a terminal, external
  installers receive no terminal input and privilege escalation never prompts;
  either fails at once and is reported. Optional desktop applications and their
  companion services are declined unless chosen.
- **Consumers.** The full installer runs every part; post-commit maintenance
  reaches them through it. No other surface establishes an owner.

<!-- /planned:startable-unattended-install -->
#### Use cases (index of feature specs)

- **project-plumbing-convergence** — `docs/local/spec/feature/reconciliation/project-plumbing-convergence.md` — converging a project's installed git hooks and docs filter driver to its declared capabilities
- **home-template-materialization** — `docs/local/spec/feature/reconciliation/home-template-materialization.md` — materializing repository-owned regular-file templates into the TeleClaude home before activation
- **template-installation** — `docs/local/spec/feature/reconciliation/template-installation.md` — rendering and naming every repository-owned template TeleClaude installs onto a machine or into a project
- **config-schema-publication** — `docs/local/spec/feature/reconciliation/config-schema-publication.md` — publishing every configuration schema once per machine into the TeleClaude home
- **launcher-code-identity** — `docs/local/spec/feature/reconciliation/launcher-code-identity.md` — signing every macOS launcher with one stable, machine-local authority, unattended, and replacing installed launchers only with a verified set built from changed inputs
<!-- planned:startable-unattended-install -->
- **fresh-machine-bootstrap** — `docs/local/spec/feature/reconciliation/fresh-machine-bootstrap.md` — taking a fresh machine, with or without a person present, to a startable, owned TeleClaude that serves its published documentation
<!-- /planned:startable-unattended-install -->


### Event subjects

Node presence and schema-governance events state no subject.


## See Also

- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered home its act concerned.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why no subject claims the event concerns no registered home, and an unknown subject makes no claim.
- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
