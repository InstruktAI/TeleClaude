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

<!-- planned-change:unattended-launcher-signing -->
- **Owns:** comparison of declared installation capabilities with observed
  machine state and selection of sanctioned convergence actions, including the
  rule deciding which material the home's history retains.
<!-- change:unattended-launcher-signing -->
- **Owns:** comparison of declared installation capabilities with observed
  machine state and selection of sanctioned convergence actions, including the
  rule deciding which material the home's history retains; and each macOS
  machine's launcher code identity — its signing authority, the signing store
  that holds it, the unlock secret that opens that store, and the record of what
  the installed launchers were built from. That state is created on the machine
  it serves, is never shared with another machine, and lies outside the home's
  retained set.
<!-- /planned-change:unattended-launcher-signing -->
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

<!-- planned:unattended-launcher-signing -->
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
- **Consumers.** The full installer, the manual launcher rebuild, the renewal
  door and the channel updater's install stage invoke the operation's entry
  point and act only on its result: a failure fails the invoking step under
  that step's own failure handling. Post-commit maintenance reaches it through
  the full installer. No consumer reads the store, the secret or the record.

<!-- /planned:unattended-launcher-signing -->
#### Use cases (index of feature specs)

- **project-plumbing-convergence** — `docs/local/spec/feature/reconciliation/project-plumbing-convergence.md` — converging a project's installed git hooks and docs filter driver to its declared capabilities
- **home-template-materialization** — `docs/local/spec/feature/reconciliation/home-template-materialization.md` — materializing repository-owned regular-file templates into the TeleClaude home before activation
- **template-installation** — `docs/local/spec/feature/reconciliation/template-installation.md` — rendering and naming every repository-owned template TeleClaude installs onto a machine or into a project
- **config-schema-publication** — `docs/local/spec/feature/reconciliation/config-schema-publication.md` — publishing every configuration schema once per machine into the TeleClaude home
<!-- planned:unattended-launcher-signing -->
- **launcher-code-identity** — `docs/local/spec/feature/reconciliation/launcher-code-identity.md` — signing every macOS launcher with one stable, machine-local authority, unattended, and replacing installed launchers only with a verified set built from changed inputs
<!-- /planned:unattended-launcher-signing -->


<!-- planned:event-origin-and-subject -->
### Event subjects

Node presence and schema-governance events state no subject.

<!-- /planned:event-origin-and-subject -->

## See Also

<!-- planned:event-origin-and-subject -->
- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered home its act concerned.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why no subject claims the event concerns no registered home, and an unknown subject makes no claim.
<!-- /planned:event-origin-and-subject -->
- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
