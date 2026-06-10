---
id: project/spec/domain/config
type: spec
domain: software-development
scope: project
visibility: public
delivered_by:
  - v2-config-cutover
description: Config bounded context — effective configuration resolved from layered
  YAML overlays. Owns the model, validation, and overlay computation. Consumed by
  every service.
---

# Config Domain Spec — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md

## What it is

The `config` bounded context owns the platform's configuration model and the computation that produces an EFFECTIVE configuration from layered YAML sources (global, project, per-person). It validates configuration against a schema, exposes the effective configuration to consumers via a read-only interface, and emits a `config.effective.updated` event when overlays change.

This context does NOT own: identity policy semantics (`identity`), workflow state (`workflow`), the authored content of snippets or artifacts (`knowledge`, `agent_artifacts`). It is the platform's foundation for "what is this machine / project / person configured to do" — nothing more.

## Canonical fields

### Ubiquitous language

**Configuration**
: The full set of declared settings for a machine, project, or person. Stored as YAML on disk; resolved into an effective configuration in memory.

**Effective configuration**
: The configuration produced by overlaying global → project → person sources, with later sources overriding earlier ones for matching keys. The output that consumers actually read.

**Overlay**
: One layer in the effective-configuration computation. Three overlays exist: global (`~/.teleclaude/teleclaude.yml`), project (`<project>/teleclaude.yml`), person (`~/.teleclaude/people/<name>/teleclaude.yml`).

**Runtime configuration**
: Per-machine settings that live in `config.yml` (separate from `teleclaude.yml`). Computer identity, agent inventory, Redis URL, daemon socket path, deployment release channel. Distinct from the YAML overlays — runtime config is one file per machine, not layered.

**Release channel** (per glossary)
: `alpha` / `beta` / `stable`. Per-machine; owned by config (lives in `config.yml`). Gates the daemon's auto-update behavior. `pinned_minor` is required when the channel is `stable`.

**Config schema**
: The typed model declaring valid configuration shape. Source of truth for what keys exist, their types, and validation rules. Implemented as Pydantic in v1, as a Rust struct + validation in v2.

**Effective-config snapshot** (optional, for history)
: A point-in-time record of the effective configuration. Persisted to `config.effective_config_snapshots` table only if history matters; otherwise the service is stateless and computes on demand.

**Person output visibility settings**
: Per-person preferences that control which non-conversational session output categories are eligible for projection on mobile/chat adapters and web/API surfaces. The settings live in the per-person overlay, not in the global `people` identity list.

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

#### PersonConfig output visibility (value object)

- **Root:** `OutputVisibilitySettings`
- **Contains:** `notifications`, `system_messages`, and `tool_calls`.
- **Invariants:**
  - Each field accepts only `null`, `off`, `mobile`, `web`, or `both`.
  - `null` means "use the role-based default", not "hide".
  - `off` hides the category on every projected surface.
  - The value object belongs to `PersonConfig.settings.output_visibility`.
  - Unknown values fail validation instead of falling through to hidden or visible behavior.
  - Projection consumers derive a `VisibilityPolicy` from these settings plus the recipient's human role and target surface.
- **Defaults:**
  - `notifications`: hidden for every role, including admins.
  - `system_messages`: visible on `mobile` and `web` for admins; hidden for members, contributors, and newcomers.
  - `tool_calls`: visible on `mobile` and `web` for admins; hidden for members, contributors, and newcomers.
- **Non-configurable categories:** tool results remain TUI-only; checkpoint messages and agent-CLI side-channel artifacts are dropped from projected surfaces; peer cross-share content remains visible on projected surfaces.

#### Runtime Configuration (aggregate)

- **Root:** `RuntimeConfig`
- **Contains:** computer identity (name, host, user, role, platform, timezone), agents inventory, Redis URL, daemon socket path, deployment release channel + pinned minor.
- **Invariants:**
  - Exactly one runtime configuration per machine. File at `config.yml` (location TBD by platform conventions).
  - Computer identity fields are immutable per machine; changing them requires re-running `make install` / wizard.
  - Release channel + pinned_minor obey the stable-channel rule (above).
- **Identifier:** the machine itself (one runtime config per machine, no further sub-identity).
- **Lifecycle:** authored and mutated through the TUI setup wizard (`telec config wizard`), which is the canonical single human-facing surface for every persisted TeleClaude setup value — initial install and idempotent re-runs alike. A non-interactive `telec config patch` surface also exists for scripted mutation; its current v1 implementation raw-merges YAML and is not part of the wizard delivery contract. Behavioural contract for the wizard surface (single setup surface, idempotent re-runs, secret hygiene, partial-resume, at-a-glance status, permissions/preflight) lives in `project/spec/feature/config/setup-wizard`.

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

Feature spec index for the `config` bounded context. Each entry names a
durable capability and points at the feature spec that carries the
Gherkin acceptance scenarios and implementation grounding. v1 entries are
inventory snapshots delivered by `inventory-v1-config`; v2 entries will
be added as `v2-config-cutover` lands the cutover work.

#### v1 features

- **Layered Overlay Resolution** — `docs/project/spec/feature/config/layered-overlay-resolution.md` — Three independent `teleclaude.yml` overlays (global, project, per-person) loaded side-by-side into an `AppConfig`; v1 does not merge them.
- **Machine Config Load** — `docs/project/spec/feature/config/machine-config-load.md` — Per-machine `config.yml` loaded at module import; deep-merged with `DEFAULT_CONFIG`, env-var expanded, optional sibling `experiments.yml` merged into the experiments list.
- **YAML Env-Var Expansion** — `docs/project/spec/feature/config/yaml-env-var-expansion.md` — `${VAR}` references substituted from `os.environ` before Pydantic or dataclass construction across every config load path; missing variables leave the literal token in place.
- **Unknown-Key Warning** — `docs/project/spec/feature/config/unknown-key-warning.md` — User-facing Pydantic models declare `extra="allow"`; unknown keys recursively logged as warnings rather than rejected. Legacy `config.yml` raises hard only for unknown `agents.*` keys.
- **Atomic Project Config Write** — `docs/project/spec/feature/config/atomic-project-config-write.md` — `save_project_config` writes via temp file + fsync + `os.replace`; dumps with `mode="json", exclude_defaults=True` to keep YAML minimal.
- **Per-Level Key Restriction** — `docs/project/spec/feature/config/per-level-key-restriction.md` — Each config level (global, project, per-person, legacy `config.yml`) rejects keys that belong to other levels via pre-validator guards.
- **Project Slug Validation** — `docs/project/spec/feature/config/project-slug-validation.md` — `project_slug` is format-validated when set; empty and whitespace-only values normalize to `None` for legacy compatibility.
- **Agents Inventory Requirement** — `docs/project/spec/feature/config/agents-inventory-requirement.md` — `config.yml:agents` is mandatory; `default` must be a known and enabled agent; at least one agent must be enabled; runtime injects the binary and tmux paths (not user-configurable).
- **Experiment Matching** — `docs/project/spec/feature/config/experiment-matching.md` — `Config.is_experiment_enabled` ORs same-name entries; agent dimension is strict (None loses), adapter dimension is optimistic (None wins) for coordinator-style queries.
- **WhatsApp Env-Var Override** — `docs/project/spec/feature/config/whatsapp-env-var-override.md` — Six `WHATSAPP_*` environment variables override YAML credential fields; the adapter auto-enables when both `phone_number_id` and `access_token` resolve to truthy values.
- **Job Schedule Contract** — `docs/project/spec/feature/config/job-schedule-contract.md` — `JobWhenConfig` requires exactly one of `every` (`<int><m|h|d>`, ≥ 1 minute) or `at` (`HH:MM` 24-hour, single or list); `weekdays` is only valid alongside `at`.
- **Stable Channel Pinning Rule** — `docs/project/spec/feature/config/stable-channel-pinning-rule.md` — Project `deployment.channel = stable` requires a non-empty `pinned_minor`; alpha and beta channels accept empty pins.
- **Integrator Cutover Gate** — `docs/project/spec/feature/config/integrator-cutover-gate.md` — `integrator.cutover.enabled = true` is rejected unless `parity_evidence_accepted = true`; rollback-on-incomplete-parity defaults on.
- **Subscription Routing** — `docs/project/spec/feature/config/subscription-routing.md` — Subscriptions are a `type`-discriminated union of `JobSubscription` and `YoutubeSubscription`; each carries a `SubscriptionNotification` with `preferred_channel` (default `telegram`).
- **Person Identity Schema** — `docs/project/spec/feature/config/person-identity-schema.md` — `PersonEntry` declares per-person identity in the global `people` list with a required non-empty stripped email, role enum, and nested expertise mapping; `proficiency` is the deprecated single-level form.
- **Runtime TTS Toggle** — `docs/project/spec/feature/config/runtime-tts-toggle.md` — `RuntimeSettings` is a separate mutable layer persisted as JSON with debounced (0.5s) writes; only `tts.enabled` is mutable today; `parse_patch` strictly rejects unknown keys and non-bool values.
- **Setup Wizard** — `docs/project/spec/feature/config/setup-wizard.md` — `telec config wizard` is the canonical single TeleClaude-owned interactive surface for every persisted setup value. Guarantees: single setup surface, idempotent re-runs, secret hygiene, partial-resume, at-a-glance status, release-channel + permissions/preflight coverage. Pending delivery of `simplify-install-flow-cleanup` + `install-wizard-enrichment`.
- **Machine Config Write** — `docs/project/spec/feature/config/machine-config-write.md` — `save_machine_config` mirrors `save_project_config`'s atomic-replace contract for the dataclass-backed machine `config.yml`. Sanctioned write path for machine-level config; v1 does not emit `config.effective.updated` from this writer. Pending delivery of `install-wizard-enrichment`.
- **Atomic Env File Write** — `docs/project/spec/feature/config/atomic-env-file-write.md` — `set_env_var` is promoted from `target.write_text(...)` to the tmp-file + flush+fsync + `os.replace` pattern so the wizard's per-section atomic-write contract holds uniformly across YAML, machine config, and `.env` surfaces. Pending delivery of `install-wizard-enrichment`.
- **Agent Env Allow List** — `docs/project/spec/feature/config/agent-env-allow-list.md` — `GlobalConfig.env_allow_list` and `ProjectConfig.env_allow_list` form the user-configurable authorization surface for ambient environment variables entering agent tmux sessions. Global entries cover local agent skills across projects; project entries add repository-specific names. The regular project `.env` remains application/runtime input; agent access requires listing each variable name explicitly.

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
- v1 `teleclaude/config/_remote_computers.py` is being retired entirely (per the `fleet-redis-discovery` inheritance in `v2-agent-runtime`); fleet topology moves out of config and into Redis self-advertisement. The schema field `remote_computers` is dropped.
- v1 `DeploymentConfig` was misplaced on `ProjectConfig`. The v2-config-cutover relocates it to runtime config (see the cutover input). Until the cutover lands, the misplacement persists.
- Validation is schema-driven, not freeform. Adding a new config field requires updating the schema in the same PR as the consumer that reads it. Unknown keys log a warning today; v2 may tighten to errors.
