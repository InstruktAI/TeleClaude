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

<!-- planned-change:lean-git-commit-scope -->

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

<!-- change:lean-git-commit-scope -->

- **Owns:** comparison of declared installation capabilities with observed
  machine state and selection of sanctioned convergence actions, including the
  home's `.gitignore`, written from the platform's home template, which decides
  what the home's history retains, and the home snapshot that records that
  history; and each macOS
  machine's launcher code identity — its signing authority, the signing store
  that holds it, the unlock secret that opens that store, and the record of what
  the installed launchers were built from. That state is created on the machine
  it serves, is never shared with another machine, and lies outside the home's
  retained set.
- **Does not own:** service lifecycle mechanics, configuration schema, or the
  application behavior of the capabilities it reconciles.
- **Published contracts:** reconciliation observations, plans, and outcomes
  consumed by sanctioned installation and service-control surfaces; the home's
  membership predicate, which is git's evaluation of the home's `.gitignore`:
  `retained` for a path the file admits, `not-retained` for one it ignores, and
  `outside` for a path beyond the home root; and the home snapshot, which the
  commit surface runs for a commit requested in the home.
- **Also published:** fleet discovery facts for this installation — which node
  is the mesh master, and which capabilities this node advertises — carried on
  the heartbeat as additive fields and readable by every peer. The context owns
  the declaration and its advertisement only; which capability a consumer
  requires before coordinating, and what it does when a peer lacks it, is that
  consumer's own contract.

<!-- /planned-change:lean-git-commit-scope -->

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

- **Consumers.** The full installer, the manual launcher rebuild and the
  renewal door invoke the operation's entry point and act only on its result: a
  failure fails the invoking step under that step's own failure handling.
  Post-commit maintenance, including the maintenance a channel update's advance
  owes, reaches it through the full installer. No consumer reads the store, the
  secret or the record.

#### Fresh-machine bootstrap

- **Decision boundary (core).** One reconciliation operation decides the
  machine's owner from the installation's owner seed, the person registry and
  whether the run has a terminal. With no person registered, a seed
  establishes its person as platform administrator, and a terminal operator
  without a seed is asked for one. A run with no terminal and no seed is
  refused. With people registered, a matching seed is a no-op, no seed needs
  nothing, and a conflicting seed is refused. A refusal writes nothing and fails
  the installation, naming the mismatch or the missing seed. The decision is
  taken as soon as the project's environment can evaluate it, before any step
  that writes configuration or the home. Its write happens after configuration
  is migrated and validated and before home activation.
- **Writes it delegates.** The owner's registration (the registry entry and the
  person's declaration) is made through config's first-person registration
  (`local/projects/teleclaude/spec/domain/config`), never through the
  configuration surface. The person home's documentation baselines are left to
  home activation, which writes them over absent targets and records them as
  its own write, and its master to the platform home's convergence
  (`local/projects/teleclaude/spec/feature/reconciliation/home-template-materialization`).
  The registration itself stays outside installation's record, as every
  registration made through the configuration surface does.
- **Startable checkout.** When the checkout has no environment settings file,
  installation writes one through config's environment-defaults operation, holding only the
  local defaults for services installation itself provisions. An existing file
  is never rewritten.
- **Install-time publication.** After home activation, installation invokes
  context's installation entry point for the installed checkout's home, which
  publishes the commit installation put in place
  (`local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`).
  Installation acts only on its result. A home that was published or was
  already current lets the installation continue. A home that was skipped, or a
  run that failed, fails the installation with publication's cause. The global
  home is not part of this step: its own publication follows its commits.
- **Unattended execution.** The installation's own tool directory is on its
  search path from the start of the run. In a run without a terminal, external
  installers receive no terminal input and privilege escalation never prompts;
  either fails at once and is reported. Optional desktop applications and their
  companion services are declined unless chosen.
- **Consumers.** The full installer runs every part; post-commit maintenance
  reaches them through it. No other surface establishes an owner.

#### DeepSeek stack convergence

- **State.** No durable state. A run owns a scratch area for its own length,
  holding the snapshot — every profile directory as found and the installed
  runtime version — and the verification gate's working directory, harness
  home and user home. A run ending upgraded, unchanged or rolled back removes the area; a run
  ending rollback incomplete keeps the snapshot and names it in its report.
  One run at a time holds a harness home.
- **Decision boundary (core).** One reconciliation core operation converges
  the DeepSeek stack. It reads the stack — the installed runtime, every
  profile's manifest, and the required plugins the installation declares — and
  refuses to change anything while another run is in progress. It orders the
  candidate runtimes, judges fit, selects the adopted set with the newest
  fitting version of each registry package and one registry requirement per
  registry plugin, and decides from the gate's verdict whether the applied set
  stays or the snapshot is restored. Every range is judged by the package
  registry's own resolution of that range against published versions, so the
  strict prerelease rule is the registry's and is never restated. Each profile
  records the adopted version of every registry package exactly, and every run
  chooses again from what is published. Its published result names the outcome; each package's previous and
  adopted version; each blocking package with its requirement and the version
  that fails it; each library advisory of the adopted set; the failed step or check; and, for a rollback that cannot
  complete, every part that still differs and where the snapshot is kept.
- **Infrastructure.** Registry queries, the global runtime installation, each
  profile's plugin manager, the profile copies and every launch the gate makes
  execute behind ports the core operation drives; they decide nothing. Every
  external tool runs without terminal input, so no vendor prompt — a
  compatibility exemption included — can be accepted on the operator's behalf,
  and the operation never asks a profile's plugin manager to grant one.
- **Verification gate.** The gate runs under a throwaway harness home of its
  own. The operator's profiles, the subject under test, and the operator's
  credentials are shared into it; the rest of the home's configuration is
  copied in; its session, storage, history and log stores start empty; and its
  hook layer is the gate's own, so the operator's hooks — TeleClaude's receiver
  among them — never fire for a gate turn and no gate turn becomes a TeleClaude
  session or history entry. Every process the gate starts also runs under a
  throwaway user home of the gate's own, so anything a profile keeps beside
  the harness home — the TUI's per-machine data, its session history and
  resume record among it — is written there and never into the operator's.
  Before the gate runs, the operation applies the installation's
  first-run-guide convergence to the operator's TUI data, then copies that
  data into the gate's user home, so the launch is checked against the
  operator's own record. Each profile is booted through
  its own app far enough to mount every plugin, and its composed configuration
  is dumped; any startup diagnostic fails the check. The launch profile runs in
  a terminal server the gate starts for itself. Its readiness is judged by the
  agent runtime's composer classification for the DeepSeek agent, which the
  gate consumes and never restates, and the gate types its prompts there. Turn
  outcomes come from the gate's own hooks: a stop hook records completion, a
  stop-failure hook records a turn error, and a prompt-submit hook returns the
  additional context of the hook turn. Every check is bounded in time. Teardown
  stops the terminal server and every process the gate started and removes
  the gate's working directory, harness home and user home, whatever the
  verdict.
- **Consumed contracts.** From the agent runtime: the DeepSeek agent
  definition's launch profile, and the composer classification of a pane
  observation for the DeepSeek agent. From this context: the installation's
  first-run-guide convergence.
- **Consumers.** The full installer installs or moves the runtime only by
  invoking the operation, declares the required plugins, and adds no plugin to
  a profile outside it; it ensures the local checkout of TeleClaude's plugins
  repository exists first. An unchanged or rolled-back outcome is reported
  without failing the rest of the installation; a rollback that cannot
  complete is reported as a failure of the DeepSeek step. Operators and agents
  run the same operation on demand through the repository's make surface.
  Post-commit maintenance reaches it through the full installer.

#### DeepSeek launch-profile creation

- **Decision boundary (core).** Whether the launch profile exists is part of
  the stack the convergence operation reads, under the name the DeepSeek agent
  definition gives it. When no profile of that name exists, the TUI joins the
  packages that must fit every candidate, and the adopted set plans the launch
  profile with the TUI and every required plugin. A planned creation is a change
  on its own, so a stack whose runtime and packages are already the newest that
  fit still adopts the set that creates it. A profile that exists, the launch
  profile among them, is planned by the same fit and reference rules as every
  installed profile, and creation never applies to it; no other profile is ever
  planned into existence.
- **Infrastructure.** The launch profile is created only by adding its planned
  packages through that profile's plugin manager, relying on the plugin
  manager's initialization of a missing profile as
  `third-party/deepseek-dsh/runtime-surface` documents it. The operation writes
  no profile file of its own.
- **Snapshot and restore.** The snapshot records which profiles existed. A
  restore removes a profile the run created; a created profile that cannot be
  removed is one of the differences a rollback-incomplete outcome names.
- **Published result.** The result of a run that keeps a created launch
  profile names that profile as created.

#### Installation

- **State.** Per machine, under the XDG data directory in the platform's own
  folder: the kept repository of the source the installation follows, one
  release per installed revision as a worktree of it, the active-release
  pointer, and the install record — the active and previous release, whether
  any migration has started since the active release became active and in
  which stores, and the outcome of the most recent
  install or rollback with its reason. All of it lies outside the platform home
  and outside any project, and the membership predicate answers `outside` for
  it.
- **Decision boundary (core).** One reconciliation core operation installs a
  revision: it refuses a target older than the active release under the release
  transitions of `local/projects/teleclaude/spec/feature/reconciliation/channel-gated-self-update`,
  prepares the release while the daemon serves, runs the release's migrations
  and opens its stores inside the stopped window, decides from the store owners'
  signals whether any migration started — counting every started migration as
  having changed state — and from that whether a failure returns to the
  previously active release or leaves the daemon stopped for a
  forward repair, switches the pointer, and records the outcome. A second
  operation rolls back: it decides from the install record whether no migration has started since the active release became active and a
  previous release exists, and otherwise refuses. Their observable contract is
  `local/projects/teleclaude/spec/feature/reconciliation/installed-releases`.
- **Infrastructure.** Git fetch and worktree operations, the release's
  environment build, the migration systems' own runners, and the atomic pointer
  switch execute behind ports the operations drive; they decide nothing. Each
  migration owner keeps its own applied state and rules
  (`local/projects/teleclaude/spec/feature/config/document-migration` for
  configuration documents) and signals, before it changes anything, that it is
  starting a migration — for ledger-recorded migrations and for those that run
  when its store is opened; an owner that cannot signal counts as having
  started one. Owners signal every migration the active release starts, during
  an install or when it first opens a store afterwards, to the install record. The operation
  opens each store through its owner's initialization and reads no domain data.
- **Live-surface binding.** The installation's live surfaces — service
  definitions, the published `telec`, agent hook commands, home-level wrappers
  and links — address the active release through its pointer; their
  relationship is `local/projects/teleclaude/design/architecture/installation`.
- **Consumers.** The bootstrap, the move off a project checkout, the channel
  reaction and `telec app install` invoke the install operation; `telec app
rollback` invokes rollback; `telec app status` reads the install record. The
  daemon's start, stop and verification are consumed from
  `local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`.

- **Assessment owed.** Beside the install record, the installation keeps the
  assessment record: the installs whose assessment is owed and the most recent
  recorded assessment, each install under its own number. The migration step
  of the release being installed records the install as owed as the stopped
  window opens, before its migrations, whichever release's install operation
  runs; the daemon emits the owed-assessment event at each start and at a fixed
  interval while an install is owed; `telec app assessed` discharges the
  installs up to the number it names.
  The event activates `sdlc/procedure/maintenance/installation/overview`
  on the installation's computer.

#### Channel convergence

- **State.** Per installation: the followed source — the remote of its kept
  repository — and the channel configuration declares; the newest admitted
  edge revision not yet installed; the release held for the installation
  inspector, when a
  release beyond the active release's compatibility series has been published;
  and the most recent convergence decision with its reason. The compatibility
  series is derived from the active release's version — the minor line while
  the major is zero, the major line from 1.0 onward — and is never declared.
- **Decision boundary (core).** One reconciliation core operation decides, for
  each signal about the followed source, whether and to what the installation
  converges. Signals from any other repository are outside its domain. On edge
  it admits a main revision announced green
  (`local/projects/teleclaude/spec/feature/integration/ci-run-outcomes`) whose
  history contains the active release's source, and keeps only the newest such
  revision. Activation begins when the install stops the daemon: until then an
  edge target that a newer admitted revision overtakes is abandoned while the
  active release keeps serving, and the newer one is installed instead, so a
  revision overtaken before its activation is never activated. On stable it admits a published release within the derived
  series; a later release beyond it is never installed by this operation: the
  operation holds the newest such release, records why, and emits the
  held-release event once per release. The admitted target is installed through
  the install operation; installing a revision at or beyond the held release
  clears the hold.
- **Signals.** Relayed green announcements and published releases of the
  source reach the operation as platform events. The operation also reads the
  source on a fixed interval: on stable its published releases, on edge the
  newest main revision `integration` establishes as green under its one
  required-check rule
  (`local/projects/teleclaude/spec/feature/integration/ci-run-outcomes`). An
  installation outside the cluster whose ingress receives the source's
  webhooks, or one that was not running when a signal was relayed, therefore
  still converges. A pushed revision is no signal on any channel.
- **Consumers.** `telec app status` reads the convergence decision and any held
  release. The held-release event activates
  `sdlc/procedure/maintenance/installation/overview` on the installation's
  computer; its held-release route carries out the release's upgrade and
  installs it through `telec app install`.

#### Use cases (index of feature specs)

- **project-plumbing-convergence** — `docs/local/spec/feature/reconciliation/project-plumbing-convergence.md` — converging a root to its declaration: a project's installed git hooks, docs filter driver and help desk, and the masters and help desks the platform home seeds
- **home-template-materialization** — `docs/local/spec/feature/reconciliation/home-template-materialization.md` — materializing the TeleClaude home's repository layer and documentation baselines before activation, and naming which home masters and help desks convergence seeds once
- **template-installation** — `docs/local/spec/feature/reconciliation/template-installation.md` — rendering and naming every repository-owned template TeleClaude installs onto a machine or into a project
- **config-schema-publication** — `docs/local/spec/feature/reconciliation/config-schema-publication.md` — publishing every configuration schema once per machine into the TeleClaude home
- **launcher-code-identity** — `docs/local/spec/feature/reconciliation/launcher-code-identity.md` — signing every macOS launcher with one stable, machine-local authority, unattended, and replacing installed launchers only with a verified set built from changed inputs

- **fresh-machine-bootstrap** — `docs/local/spec/feature/reconciliation/fresh-machine-bootstrap.md` — taking a fresh machine, with or without a person present, to a startable, owned TeleClaude that serves its published documentation

- **deepseek-stack-convergence** — `docs/local/spec/feature/reconciliation/deepseek-stack-convergence.md` — moving the DeepSeek runtime, its TUI and every plugin to the newest mutually compatible set, verified and restorable, without pinning or dropping a plugin

- **installed-releases** — `docs/local/spec/feature/reconciliation/installed-releases.md` — running the platform from installed releases apart from the project and the platform home, installing forward, rolling back one migration-free step, and operating the installation through `telec app`

### Event subjects and origins

Node presence events state the node as subject, and schema-governance events the
schema proposal they concern; neither states an origin.

The held-release event states as subject the release it holds — the followed
source and the release's version — and states no origin: the installation's
convergence happens in no registered project, person, or company.

The owed-assessment event states as subject the newest owed install — its
number, revision and when it became owed — and states no origin: the
installation belongs to no registered project, person, or company.

### Governing designs and decisions

- `local/projects/teleclaude/design/architecture/installation` — the installation, its releases and the install act
- `local/projects/teleclaude/design/architecture/release-publication` — release candidates and their publication
- `local/projects/teleclaude/design/architecture/home-repository` — the home's retained set and local-only history
- `local/projects/teleclaude/adr/0024-reconciliation-bounded-context` — fleet convergence as its own context
- `local/projects/teleclaude/adr/0025-two-layer-migration-model` — separating aggregate upcasting from schema migration
- `local/projects/teleclaude/adr/0026-cross-version-fleet-compatibility` — interoperation across a multi-version fleet
- `local/projects/teleclaude/adr/0041-agents-own-daemon-lifecycle-via-make` — agents operating the daemon lifecycle
- `local/projects/teleclaude/adr/0083-retain-node-toolchain-for-non-frontend-tooling` — keeping the Node toolchain in the installer
- `local/projects/teleclaude/adr/0124-maintenance-replaces-the-daemon-inside-a-stopped-window` — replacing the daemon inside a stopped window
- `local/projects/teleclaude/adr/0127-maintenance-runs-serving-tolerant-steps-after-the-verified-start` — serving-tolerant steps after the verified start
- `local/projects/teleclaude/adr/0128-maintenance-actions-declare-serving-tolerance-per-action` — serving tolerance declared per maintenance action
- `local/projects/teleclaude/adr/0129-overlays-can-declare-maintenance-actions-that-run-while-the-daemon-serves` — overlays declaring serving-tolerant maintenance actions
- `local/projects/teleclaude/adr/0130-the-platform-runs-from-an-installation-not-its-project` — the platform running from an installation

## See Also

- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered project, person, or company its act happened in.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why no subject claims the event concerns no registered home, and an unknown subject makes no claim.

- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md — why each event names the thing it is about as its subject, separately from its origin.

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
