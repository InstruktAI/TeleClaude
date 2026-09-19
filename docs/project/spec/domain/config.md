---
visibility: internal
description: Frozen v1 ownership anchor for file-backed configuration loading, validation, and operator editing.
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
- **Runtime authority:** configuration is loaded through
  `teleclaude/runtime/config.py`; externally supplied configuration values enter
  through YAML placeholder expansion at the load boundary, and consumers read
  the resolved values only from the typed configuration aggregate. Consumers
  neither consult the process environment nor invent fallback values.
- **Maintenance stance:** see `project/spec/domain/glossary`. File-backed configuration is not
  extended for vNext needs.

### Ownership boundary

- **Owns:** configuration schema, loading, validation, normalization, and
  operator mutation of declared settings.
- **Does not own:** business defaults invented by consumers or lifecycle policy
  for systems configured by those settings.
- **Published contracts:** validated configuration models and `telec config`
  commands; consumers never reinterpret missing or invalid values.
<!-- planned:move-discord-reflection-state-to-db -->
- **Also owns:** every mutation of machine configuration. Agents use the
  `telec config` surface, and runtime consumers submit named semantic operations;
  neither receives backing-file write authority. The config context holds the
  lock across reading the latest document, applying the operation, validating
  the complete candidate, and atomically replacing the file.
- **Does not own:** provider-returned identifiers or other observed external
  state. The bounded context that observes such state persists it through its
  own state contract rather than through machine configuration.
<!-- /planned:move-discord-reflection-state-to-db -->
- **Also owns:** the person tier's voice-room declaration as typed settings —
  the voice bot credential reference and the private voice channel. These are
  declared fields rather than tolerated extras, so a missing or malformed value
  is rejected at validation instead of surfacing as absent capability at
  runtime. The credential resolves only through the person overlay's own
  tier-local environment; no global or foreign-person fallback exists, and the
  resolved value is never logged or persisted. Which computer acts on the
  declaration is not a person setting: the machine configuration's existing
  `computer.is_master` — exactly one in the mesh — already names the one
  computer that provisions this bot's shared Discord structure, and voice
  ownership follows it. Owning the declaration is not owning what it means.
- **Also owns:** the machine TTS configuration's per-service `discord_voice`
  declaration — one name drawn from that service's own `voices` list, with the
  first entry as the template default, and absent for a service that declares
  no voices — as a typed setting validated against the list it names. What the
  room does with it belongs to the TTS design.
<!-- planned:personal-assistant-launch -->
- **Also published:** person-workspace containment — whether a given path lies
  inside any person's workspace, answered for the composed destination rather
  than for a directory's own name. Consumers call it and never read the
  person-directory layout themselves.
<!-- /planned:personal-assistant-launch -->
- **Also owns:** the company tier's organizational roster — which people belong
  to a company, the role each holds, and which of that company's projects each
  is assigned to — as a declared setting: its schema, its validation against
  registered companies and projects, and its operator mutation. Owning the
  declaration is not owning what the facts mean; resolution belongs to
  `project/spec/domain/identity`.
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
  `project/spec/feature/config/tier-permissions`.
- **Also owns:** two further declarations and their validation: the person
  overlay's identity claim naming the registered person its workspace belongs
  to, and the project overlay's declared owner — a company or a person, at
  most one, with no owner a valid state. Owning the declarations is not owning
  what they mean: what an accepted person binding confers belongs to
  `project/spec/domain/identity`, and no permission follows from ownership.
  The behavioral contracts are
  `project/spec/feature/identity/person-context-binding` and
  `project/spec/feature/config/project-ownership`.
- **Also does not own:** where a project's shared state lives. That rule reads
  the checkout-and-worktree relation rather than any configuration, and belongs
  to the context that creates linked worktrees and defines what they share.
  Carrying a configuration file is not an ownership basis. The decomposition is
  `project/design/architecture/config-tier-resolution`.

#### Use cases (index of feature specs)

- **project-registry** — `docs/project/spec/feature/config/project-registry.md` — which checkout is recorded for an adopted project, and which paths never write the registry


## See Also

- docs/project/spec/teleclaude-config.md
- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
