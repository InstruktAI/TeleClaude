---
visibility: internal
description: V1 configuration ownership for declaration loading, validation, normalization and operator editing.
---

# Config Domain Spec — Spec

## What it is

The v1 config area owns loading, validation, normalization, and operator editing
for the appliance's file-backed configuration. These files remain authoritative
for v1 runtime behavior while all new configuration architecture lives in
TeleClaudeNext.

## Canonical fields

- **Schema authority:** `teleclaude/config/` and the published configuration
  schema.
- **Operator surfaces:** `telec config` commands and the TUI configuration view.
- **Implementation roots:** `teleclaude/config/`.

- **Runtime authority:** configuration is loaded through
  `teleclaude/runtime/config.py`; externally supplied configuration values enter
  through YAML placeholder expansion at the load boundary, and consumers read
  the resolved values only from the typed configuration aggregate. Consumers
  neither consult the process environment nor invent fallback values.

- **Maintenance stance:** see `local/projects/teleclaude/spec/domain/glossary`. File-backed configuration is not
  extended for vNext needs.

### Ownership boundary

- **Owns:** configuration schema, loading, validation, normalization, and
  operator mutation of declared settings.
- **Does not own:** business defaults invented by consumers or lifecycle policy
  for systems configured by those settings.
- **Published contracts:** validated configuration models and `telec config`
  commands; consumers never reinterpret missing or invalid values.
- **Also owns:** every mutation of machine configuration. Agents use the
  `telec config` surface, and runtime consumers submit named semantic operations;
  neither receives backing-file write authority. The config context holds the
  lock across reading the latest document, applying the operation, validating
  the complete candidate, and atomically replacing the file.
- **Does not own:** provider-returned identifiers or other observed external
  state. The bounded context that observes such state persists it through its
  own state contract rather than through machine configuration.
- **Also owns:** the person tier's voice-bot declaration as a typed credential
  reference. The semantic `telec config person discord-voice-bot`
  operation copies the currently resolved machine Discord credential into the
  person's owner-only environment under the canonical `DISCORD_TOKEN` name and
  persists only `${DISCORD_TOKEN}` in the overlay. On a computer whose person
  environment holds no value for it, the token is absent and the voice bot does
  not run there. The live private voice channel is provider-returned
  state resolved by integration from the identified person's voice-state event,
  not a configuration field or fallback. Which computer acts on the declaration
  is not a person setting: the machine configuration's existing
  `computer.is_master` — exactly one in the mesh — already names the one
  computer that provisions this bot's shared Discord structure, and voice
  ownership follows it. Owning the declaration is not owning what it means.
- **Also owns:** the machine TTS configuration's per-service `discord_voice`
  declaration — one name drawn from that service's own `voices` list, with the
  first entry as the template default, and absent for a service that declares
  no voices — as a typed setting validated against the list it names. What the
  room does with it belongs to the TTS design.
- **Also owns:** the company tier's organizational roster — which people belong
  to a company, the role each holds, and which of that company's projects each
  is assigned to — as a declared setting: its schema, its validation against
  registered companies and projects, and its operator mutation. Owning the
  declaration is not owning what the facts mean; resolution belongs to
  `local/projects/teleclaude/spec/domain/identity`.
- **Also published:** the context-root resolver — which tier governs an
  invocation, read from the nearest ancestor configuration file's own
  declaration. Consumers call it and never walk the ancestor chain or read a
  tier declaration themselves.
- **Also published:** the tier-permission answer — for a root's declared tier,
  whether it establishes an invocation context, whether its material
  participates in a named surface from the closed surface set, and whether it
  carries the optional project subscriptions. Only the project tier's
  subscription answer reads that overlay's capability declaration; no overlay
  is parsed as another tier's shape to answer any of the three. Consumers ask
  this contract and never derive a permission from a path, a repository, or a
  foreign tier's default. The behavioral contract is
  `local/projects/teleclaude/spec/feature/config/tier-permissions`.
- **Also owns:** two further declarations and their validation: the person
  overlay's identity claim naming the registered person its workspace belongs
  to, and the project overlay's declared owner — a company or a person, at
  most one, with no owner a valid state. Owning the declarations is not owning
  what they mean: what an accepted person binding confers belongs to
  `local/projects/teleclaude/spec/domain/identity`, and no permission follows from ownership.
  The behavioral contracts are
  `local/projects/teleclaude/spec/feature/identity/person-context-binding` and
  `local/projects/teleclaude/spec/feature/config/project-ownership`.
- **Also does not own:** where a project's shared state lives. That rule reads
  the checkout-and-worktree relation rather than any configuration, and belongs
  to the context that creates linked worktrees and defines what they share.
  Carrying a configuration file is not an ownership basis. The decomposition is
  `local/projects/teleclaude/design/architecture/config-tier-resolution`.

- **Also owns:** what the scheduler hands a job's launch — the job's declared
  name, the entry procedure its `job` pointer names, and the declaration's
  candidate order and thinking mode — because those execute the configured job
  declaration and change when that job model changes. `agent_runtime` consumes
  them through the procedure-entry contract and owns the session launch; the
  cron process is a mechanical host and owns neither the facts nor the job
  rule.

- **Also owns:** schema strictness as a property of the configuration models
  themselves. Every configuration model rejects undeclared keys by its own
  declaration, so a load path that forgets to ask for strictness still gets it,
  and the boundary reaches every model reachable from a configuration
  aggregate — including those a neighbouring context declares. Consumers never
  supply strictness as a validation argument. The behavioral contract is
  `local/projects/teleclaude/spec/feature/config/unknown-key-warning`.

- **Also owns:** an inbound event source's declaration — made in the
  configuration of the home it concerns, with its signing secret referenced from
  that home's own `.env` — and the answer to which sources a registered home
  declares. It also answers, on each computer, whether a registered company,
  person, or project is present there and where its folder is — the company's
  home folder, the person's folder, or the project's checkout — which procedure
  activation consults on the computer that emitted an event before starting an
  agent in that home. Owning the declarations and the registry answers is not
  owning what a company context means, which belongs to
  `local/projects/teleclaude/spec/domain/identity`, or what a session does in a
  home, which belongs to `local/projects/teleclaude/spec/domain/agent_runtime`.

- **Also owns:** a person's notification interests — their shape, the starting
  interests each role receives when a person is created, their convergence for
  configuration that predates them, their validation, and the published answer
  to whether a person's interests select an event type
  (`local/projects/teleclaude/spec/feature/config/notification-interests`).
  Validation answers whether a category names a published domain from the
  registered projects' publishing declarations, and `teleclaude` is reserved:
  no project publishes a domain by that name. The consumers that tell people
  read interests through that answer and never parse them.

- **Also published:** referent resolution — whether a company, person,
  project, or documentation domain a declaration or request names is
  registered on this computer, and the one refusal for one that is not,
  naming what is missing, where, and the registration surface that supplies it
  (`local/projects/teleclaude/spec/feature/config/referent-resolution`). Every
  consumer that meets such a name resolves it through this answer and never
  restates the condition in its own words.

**Configuration commands execute in the addressed daemon.** UI clients reach
the configuration API, which constructs internal configuration commands; the
CLI constructs the same commands for submission to the daemon. The configuration
owner executes them under the same target clearance for either ingress
(`local/projects/teleclaude/spec/feature/identity/configuration-target-clearance`).
The shared editor contract supplies resolved, defaulted, masked field values and
accepts field edit intent
(`local/projects/teleclaude/spec/feature/config/kind-addressed-configuration`,
Shared configuration editor). The request's computer selects the daemon that
owns execution
(`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`).

The TUI configuration view reaches configuration only through these daemon
requests; it holds no write authority over a backing file
(`local/projects/teleclaude/design/architecture/api-server`). An environment
request names the environment it changes — the machine's, the global
configuration's, or one person's — and sets or clears one variable there. A
person's environment is that person's personal MCP secret store. The request is
cleared as a patch of the subject that owns that environment: the computer for
the machine's, global configuration for the global one, and that person for
theirs. A value that is the configuration mask leaves its variable as stored,
as a patch carrying the mask leaves its field
(`local/projects/teleclaude/spec/feature/config/kind-addressed-configuration`
UC-KAC20).

**While no daemon serves this machine, configuration commands execute in the
invoking process.** When a request addresses this computer and no daemon serves
it — before the platform's first start, or while it is stopped — the CLI and
the TUI configuration view execute the same configuration commands through this
context's own operations in their own process, under the same target clearance
and editor contract. Nothing else about the command changes. Once a daemon
serves the machine, every command executes in it, so the platform can be
configured to the point where it starts
(`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`).

#### Use cases (index of feature specs)

- **project-registry** — `docs/local/spec/feature/config/project-registry.md` — which checkout is recorded for an adopted project, and which paths never write the registry

- **referent-resolution** — `docs/local/spec/feature/config/referent-resolution.md` — how a named company, person, project, or domain resolves on one computer, and the one refusal for one that is not registered there

### Installation registration and environment defaults

Installation submits two named operations to the config context:

- **First-person registration.** It writes the person's registry entry and the
  person's declaration under the same lock, validation and atomic replacement as
  every configuration mutation, and creates nothing else in the person's home.
  It accepts only an empty registry and refuses otherwise, leaving the registry
  unchanged. The home's template layer belongs to installation's home
  materialization. Initializing a person through `telec config` still scaffolds
  that person's home
  (`local/projects/teleclaude/spec/feature/config/kind-addressed-configuration`
  UC-KAC12).
- **Environment defaults.** When the platform home has no machine environment
  settings file, it creates one there — a real file every installed release
  reads, never inside a code tree — through the atomic environment writer
  (`local/projects/teleclaude/spec/feature/config/atomic-env-file-write`), holding
  only the supplied local-service defaults. An existing file is never touched.

Neither operation passes configuration clearance: their caller is installation,
not a configuration-surface caller.

### Personal MCP secret store

The config context owns the opaque personal MCP secret store beside each typed
person overlay. The canonical person slug selects the store; safe reads require
an owner-only regular file, and missing or unsafe storage is distinguished from
a missing key. Inventory exposes key names, set state, and registry requirement
provenance without values.

Keep performs no write. Replace and clear use locked atomic targeted mutation
and preserve every unrelated key and line. Runtime and TUI consumers use this
published contract and never parse the store or consult the process environment
directly.

The inventory is also a daemon request on the person subject, and replacing or
clearing a key is that person's environment request, both under the person's
configuration target clearance. A UI reaches the store only through them.

### Membership declaration changes

The config context publishes, inside each daemon, a notice whenever a
declaration that identity's reach is built from changes on this computer: the
global person registry and its platform roles, a company's roster and its
project assignments, a person's declaration, the project registry, and a
project's declared owner. A change applied through `telec config` or edited in
the backing file is noticed alike. Config first brings its own published answers
that read those declarations — the project catalog and ownership among them —
up to date, and only then publishes the notice, so a consumer that rebuilds on
the notice reads the changed declarations. The notice names no consumer and
carries no interpretation; identity invalidates every reach a long-lived consumer holds on
it, so the next listing and every later live push read the changed declaration
(`local/projects/teleclaude/spec/domain/identity`). A request-scoped consumer resolves
reach per request and needs no notice.

### Event subjects and origins

Every platform event config emits states as its subject and origin what its act
concerned:

- a job run's outcome: the job, one thing across all its runs, with the project
  the run executes for as origin. A globally published job is a separate job in
  each subscribing project. Every job run executes for a registered project; an
  outcome recorded before runs were keyed by project, whose project cannot be
  recovered from its record, states an unknown origin.
- an effective configuration change: the configuration that changed, with the
  project whose configuration it is as origin. A machine or global configuration
  change has no origin.

### Governing designs and decisions

- `local/projects/teleclaude/design/architecture/config-tier-resolution` — which configuration tier governs an invocation
- `local/projects/teleclaude/design/architecture/feature-flags` — feature flags and experiments
- `local/projects/teleclaude/adr/0027-feature-id-capability-gating` — gating cross-node behavior behind feature ids
- `local/projects/teleclaude/adr/0077-runtime-catalog-is-separate-from-machine-settings` — the runtime catalog apart from machine settings
- `local/projects/teleclaude/adr/0099-address-configuration-by-kind` — addressing configuration by kind

## See Also

- docs/local/adr/0105-event-access-follows-the-subject-its-producer-states.md — why each event states the registered project, person, or company its act happened in.
- docs/local/adr/0109-an-event-that-cannot-establish-its-subject-says-so.md — why no subject claims the event concerns no registered home, and an unknown subject makes no claim.

- docs/local/adr/0114-events-take-the-cloudevents-attribute-model.md — why each event names the thing it is about as its subject, separately from its origin.
- docs/local/adr/0117-a-platform-event-type-names-the-state-it-reports.md — why the subject of an event that reports a state is the thing whose state it is.

- docs/local/spec/teleclaude-config.md
- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
