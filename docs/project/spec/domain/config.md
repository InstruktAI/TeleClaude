---
id: project/spec/domain/config
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by: [v2-config-cutover]
description: Config bounded context — effective configuration resolved from layered YAML overlays. Owns the model, validation, and overlay computation. Consumed by every service.
---

# Config Domain Spec — Spec

## Required reads

- @docs/global/software-development/principle/domain-driven-design.md
- @docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The `config` bounded context owns the platform's configuration model and the computation that produces an EFFECTIVE configuration from layered YAML sources (global, project, per-person). It validates configuration against a schema, exposes the effective configuration to consumers via a read-only interface, and emits a `config.effective.updated` event when overlays change.

This context does NOT own: identity policy semantics (`identity`), workflow state (`workflow`), the authored content of snippets or artifacts (`knowledge`, `agent_artifacts`). It is the platform's foundation for "what is this machine / project / person configured to do" — nothing more.

## Canonical fields

### Ubiquitous language

**Configuration**
:  The full set of declared settings for a machine, project, or person. Stored as YAML on disk; resolved into an effective configuration in memory.

**Effective configuration**
:  The configuration produced by overlaying global → project → person sources, with later sources overriding earlier ones for matching keys. The output that consumers actually read.

**Overlay**
:  One layer in the effective-configuration computation. Three overlays exist: global (`~/.teleclaude/teleclaude.yml`), project (`<project>/teleclaude.yml`), person (`~/.teleclaude/people/<name>/teleclaude.yml`).

**Runtime configuration**
:  Per-machine settings that live in `config.yml` (separate from `teleclaude.yml`). Computer identity, agent inventory, Redis URL, daemon socket path, deployment release channel. Distinct from the YAML overlays — runtime config is one file per machine, not layered.

**Release channel** (per glossary)
:  `alpha` / `beta` / `stable`. Per-machine; owned by config (lives in `config.yml`). Gates the daemon's auto-update behavior. `pinned_minor` is required when the channel is `stable`.

**Config schema**
:  The typed model declaring valid configuration shape. Source of truth for what keys exist, their types, and validation rules. Implemented as Pydantic in v1, as a Rust struct + validation in v2.

**Effective-config snapshot** (optional, for history)
:  A point-in-time record of the effective configuration. Persisted to `config.effective_config_snapshots` table only if history matters; otherwise the service is stateless and computes on demand.

### Aggregates

#### Configuration (aggregate)

- **Root:** `EffectiveConfig`
- **Contains:** the three overlay sources (`GlobalConfig`, `ProjectConfig`, `PersonConfig`), the runtime configuration (`RuntimeConfig`), and the resolved key-value tree.
- **Invariants:**
  - Effective configuration is deterministic given the same overlay inputs: same files in, same effective configuration out.
  - Required fields (per schema) MUST be present in the effective configuration; absence is a hard validation error, not a silent default.
  - Overlay precedence is strict: person overrides project overrides global. No interleaving.
  - When `release_channel = stable`, `pinned_minor` MUST be non-empty.
  - The schema is the only source of which keys are valid. Unknown keys in YAML are a validation warning (not silently ignored, not a hard error in v1; v2 may tighten).
- **Identifier:** the combined (`project_path`, `person_name`) tuple. Global-only computation when both are absent.
- **Lifecycle:** computed on demand; cached in-memory by consumers per their own caching policy. Recomputed when any overlay file changes (`config.effective.updated` event fires).

#### Runtime Configuration (aggregate)

- **Root:** `RuntimeConfig`
- **Contains:** computer identity (name, host, user, role, platform, timezone), agents inventory, Redis URL, daemon socket path, deployment release channel + pinned minor.
- **Invariants:**
  - Exactly one runtime configuration per machine. File at `config.yml` (location TBD by platform conventions).
  - Computer identity fields are immutable per machine; changing them requires re-running `make install` / wizard.
  - Release channel + pinned_minor obey the stable-channel rule (above).
- **Identifier:** the machine itself (one runtime config per machine, no further sub-identity).
- **Lifecycle:** authored once during initial install via the TUI wizard; mutated via `telec config patch` (which validates against schema before persisting).

### Domain events emitted

#### `config.effective.updated`

- **Producer:** `config`
- **Emitted when:** any overlay file changes (filesystem watcher detects modification of `~/.teleclaude/teleclaude.yml`, a project's `teleclaude.yml`, a person's `teleclaude.yml`, or `config.yml`) AND the recomputed effective configuration differs from the previous one.
- **Payload:**
  - `scope` — `global` | `project:<path>` | `person:<name>` | `runtime`
  - `changed_keys` — list of key paths whose values changed
  - `version` — monotonic counter incremented per emission
- **Visibility:** CLUSTER (every service that caches config must invalidate)
- **Known consumers:** every service that reads configuration AND caches it (most services do); the event triggers cache invalidation and reread on next access. Specific consumers: `daemon` startup config loader, `cli` per-invocation config loader, `telec-tui` (config wizard view), `integration` (per-provider settings), `agent_runtime` (per-agent settings).
- **Idempotency key:** `(scope, version)`. Consumers track the latest version they've applied; older versions are silently dropped.
- **Posture:** `commit-then-emit` — the YAML file change is the commit; the event fires after read confirms a new effective config.

### Domain events consumed

None. Config is a foundation context with no upstream domain — it watches the filesystem and reacts only to file changes, not to other services' events.

### Use cases

#### UC-CFG-1: Daemon resolves effective configuration at startup

```
Given the daemon binary is launching
And global, project, and runtime YAML files exist on disk
When the daemon's config loader runs
Then the config service reads all overlay sources
And applies overlay precedence (person → project → global)
And validates against the schema
And returns an EffectiveConfig that the daemon uses for the rest of its lifetime (or until config.effective.updated fires)
```

#### UC-CFG-2: Operator changes a configuration value via the TUI wizard

```
Given the TUI config wizard is open
And the operator changes a configuration value (e.g., adds a person to the people list)
When the operator confirms the change
Then the wizard calls the config service to validate the new effective configuration
And on validation success, the wizard writes the change to the appropriate YAML file
And the filesystem change triggers config.effective.updated
And every consuming service invalidates its cache
```

#### UC-CFG-3: CLI applies a patch with validation

```
Given an agent runs `telec config patch --yaml '<partial yaml>'`
When the patch command runs
Then the config service merges the patch into the appropriate YAML source
And validates the resulting full effective configuration against the schema
And on validation failure, the patch is rejected with a clear error naming the violated rule
And on validation success, the patch is persisted to disk
And config.effective.updated fires
```

#### UC-CFG-4: Stable-channel rule enforcement

```
Given a runtime configuration sets release_channel to stable
And pinned_minor is empty
When the config service computes the effective runtime configuration
Then validation fails with the stable-channel rule message
And the change is rejected before the file is written
```

#### UC-CFG-5: Deployment executor confirms config still loads post-pull

```
Given the deployment executor has just pulled a new release
When the executor restarts the daemon
Then it first asks the config service to compute the effective configuration
And on validation failure, the executor halts the restart and surfaces the error
And on success, the daemon restarts with the validated configuration
```

### Context map position

- **Open Host Service to every domain context** — config exposes the effective configuration via a stable read interface. Every other service reads what it needs at startup and on `config.effective.updated`. Config does not know its consumers; consumers know what configuration keys they need.
- **No upstream contexts** — config is a spine context with no dependencies on other domain services. It reads from the filesystem only.
- **Anti-corruption layer with v1 (during migration)** — v1 `teleclaude/config/` module shape (Pydantic models) is preserved by the v2 shim during the migration window. The ACL converts the v2 Rust struct into the v1 Pydantic shape so existing consumers don't need code changes. ACL lives at `crates/config/src/v1_compat.rs` (planned). Disappears when `v2-config-cutover` lands.

## Allowed values

- `release_channel`: `alpha`, `beta`, `stable`.
- `overlay_scope` (in `config.effective.updated` payload): `global`, `project:<path>`, `person:<name>`, `runtime`.

## Known caveats

- Config persistence is filesystem-first. Postgres is OPTIONAL (`effective_config_snapshots` table) and only used if effective-config history must be queryable across time. Until that use case surfaces, the service is stateless and config "lives" in YAML.
- The `~30+ consumer surface` in v1 is the broadest of any service. The v2 shim's job is to keep that surface byte-stable during migration; consumer code changes happen gradually, not as part of the cutover.
- v1 `teleclaude/config/_remote_computers.py` is being retired entirely (per the `fleet-redis-discovery` inheritance in `v2-daemon-narrow`); fleet topology moves out of config and into Redis self-advertisement. The schema field `remote_computers` is dropped.
- v1 `DeploymentConfig` was misplaced on `ProjectConfig`. The v2-config-cutover relocates it to runtime config (see the cutover input). Until the cutover lands, the misplacement persists.
- Validation is schema-driven, not freeform. Adding a new config field requires updating the schema in the same PR as the consumer that reads it. Unknown keys log a warning today; v2 may tighten to errors.
