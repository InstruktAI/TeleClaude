---
delivered_by:
  - v2-config-cutover
description: Config bounded context — effective configuration resolved from layered
  YAML overlays. Owns the model, validation, and overlay computation. Consumed by
  every service.
visibility: public
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

: One layer in the effective-configuration computation. Three overlays exist: global (`~/.teleclaude/teleclaude.yml`), project (`<project>/teleclaude.yml`), person (`~/.teleclaude/people/<slug>/teleclaude.yml`).

**Runtime configuration**

: The CORE TeleClaude platform/daemon operational configuration — per-machine settings that live in `config.yml`: computer identity, agent inventory, Redis URL, daemon socket path, deployment release channel, and the workflow autostart policy. It is distinct in both file and purpose from the `teleclaude.yml` overlays (global / project / person), which carry BUSINESS configuration — people, business domains, and project/per-person settings. The boundary is operational vs. business: runtime config governs how this machine's platform runs, is one file per machine, and is not layered; the overlays govern what the business has the platform do, and are layered.

**Release channel** (per glossary)
: `alpha` / `beta` / `stable`. Per-machine; owned by config (lives in `config.yml`). Gates the daemon's auto-update behavior. `pinned_minor` is required when the channel is `stable`.

**Config schema**
: The typed model declaring valid configuration shape. Source of truth for what keys exist, their types, and validation rules. Implemented as Pydantic in v1, as a Rust struct + validation in v2.

**Effective-config snapshot** (optional, for history)
: A point-in-time record of the effective configuration. Persisted to `config.effective_config_snapshots` table only if history matters; otherwise the service is stateless and computes on demand.

**Person output visibility settings**
: Per-person preferences that control which non-conversational session output categories are eligible for projection on mobile/chat adapters and web/API surfaces. The settings live in the per-person overlay, not in the global `people` identity list.

**Workflow autostart policy**

: Per-machine daemon runtime-config value (in `config.yml` / `RuntimeConfig`, see the Runtime Configuration aggregate) read by workflow's lifecycle runner to decide which todo kinds may auto-enter the **work lane** — the execution runtime, at the `prepared → build_started` transition. It is a global operator safety switch — not a layered overlay value and not todo state — strictly per-machine, with no project or per-person override. It gates only work-start: **preparation** (kind-discovery and the prepare lane up to `prepared`) always auto-dispatches regardless of autostart, because prep is always needed and agents park at the human approval gates. Changing it affects future runner evaluations without rewriting existing todo rows. Defaults are off for every kind (`feature=false`, `change=false`, `bug=false`, `task=false`): an unconfigured machine still prepares work, but never auto-starts it until an operator enables a kind.

**Workflow runner mode**

: Per-machine daemon runtime-config value (`workflow.runner` in `config.yml` / `RuntimeConfig`), the master switch sitting above the per-kind autostart toggles, with values `autostart` and `manual` (default `autostart`). It governs whether the lifecycle runner performs **any** autonomous dispatch. Under `autostart`, the runner evaluates and dispatches normally — preparation auto-dispatches for every kind and work-start is gated per kind by the autostart toggles. Under `manual`, the runner performs **no** autonomous dispatch at all — prepare, work, and kind-discovery are all frozen — and responds only to manual start events (`telec todo work/prepare`, the TUI START, headless adoption), so every todo progresses by hand. The mode gates only the autonomous path; a manual start is never gated by it. A change emits `config.effective.updated`, and the runner re-evaluates affected projects on its next wake.

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
  - Workflow autostart policy is per-machine runtime configuration owned solely by `config.yml` (the Runtime Configuration aggregate), not a layered overlay value. The workflow runner may read it, but workflow may not invent undeclared fallback keys or silently treat missing schema fields as enabled; defaults are provided by the config schema itself. Project and per-person overlays carry no autostart key and cannot narrow or widen it. A runtime-config update emits `config.effective.updated`; workflow re-evaluates affected projects on the next runner wake-up.
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

<!-- planned:tui-todo-session-cross-navigation -->
#### PersonConfig chip color (value object)

- **Root:** `PersonChipColor`
- **Contains:** `background` and `text`, each a `light`/`dark` pair of optional color strings.
- **Invariants:**
  - The value object belongs to `PersonConfig.color`; the whole block, each nested model, and every leaf are independently optional and default to `None`.
  - A `None` leaf is not a stored color — it signals the renderer to supply its theme-derived default for the active mode; a set leaf is honored verbatim with no override.
  - Setting a single leaf instantiates the missing intermediate models on demand, so siblings stay `None`.
  - No contrast validation: any color string is accepted per leaf; readability is the operator's responsibility.
  - Personalization lives in the person-owned overlay (`PersonConfig`), not the admin-governed global `people` list (`PersonEntry`).
- **Lifecycle:** authored and mutated through the Configuration People subtab, which reflects the four color leaves as editable fields and persists edits to the person's overlay file. Behavioral contract and Gherkin live in `project/spec/feature/config/person-chip-color`; the chip render and theme-derived defaults live in `project/spec/feature/tui/todo-session-cross-navigation`.
<!-- /planned:tui-todo-session-cross-navigation -->

#### Runtime Configuration (aggregate)

- **Root:** `RuntimeConfig`

- **Contains:** computer identity (name, host, user, role, platform, timezone), agents inventory, Redis URL, daemon socket path, deployment release channel + pinned minor, the workflow autostart policy (per-kind auto-dispatch toggles read by the lifecycle runner; off for every kind by default), the `workflow.runner` master mode (`autostart` | `manual`, default `autostart`) that gates whether the runner performs any autonomous dispatch, and `max_todo_dispatch` (the per-machine cap on concurrent auto-dispatched lifecycle sessions; default 5).

- **Invariants:**
  - Exactly one runtime configuration per machine. File at `config.yml` (location TBD by platform conventions).
  - Computer identity fields are immutable per machine; changing them requires re-running `make install` / wizard.
  - Release channel + pinned_minor obey the stable-channel rule (above).
  - `max_todo_dispatch` is a per-machine load limit (default 5) read by the lifecycle runner: the runner auto-dispatches only while the count of live auto-dispatched lifecycle sessions on this machine is below it. It bounds machine load only; it never gates a manual `telec todo work/prepare` start.
- **Identifier:** the machine itself (one runtime config per machine, no further sub-identity).
- **Lifecycle:** authored and mutated through the TUI setup wizard (`telec config wizard`), which is the canonical single human-facing surface for every persisted TeleClaude setup value — initial install and idempotent re-runs alike. A non-interactive `telec config patch` surface also exists for scripted mutation; its current v1 implementation raw-merges YAML and is not part of the wizard delivery contract. Behavioural contract for the wizard surface (single setup surface, idempotent re-runs, secret hygiene, partial-resume, at-a-glance status, permissions/preflight) lives in `project/spec/feature/config/setup-wizard`.

#### Ingress Configuration (value object)

- **Root:** `IngressConfig`
- **Contains:** `enabled` (bool, default false), `bind` (socket address), `allowed_source` (set of real peer addresses), and `providers` (map keyed by provider name; each `providers.<name>.secret` is that provider's verification secret).
- **Invariants:**
  - Ingress configuration is per-machine configuration read by the daemon at startup.
  - `enabled=false` means the daemon registers no ingress service loop and ignores absent `bind`, `allowed_source`, and provider entries.
  - `enabled=true` requires `bind` and at least one `allowed_source`; absence is a hard validation error.
  - `bind` names a concrete LAN or boundary-facing address. Loopback addresses and the promiscuous `0.0.0.0` bind fail validation.
  - `allowed_source` contains the real TCP peer addresses accepted by the ingress; forwarded headers are not accepted as source identity.
  - Every configured provider requires a non-empty `providers.<name>.secret`. An enabled provider with no secret fails validation.
  - Provider names resolve against integration's provider registry. Unknown provider names fail closed at request handling.
  - Secrets are validation and verification inputs only; config events, logs, and relay payloads never include the secret value.
- **Identifier:** the machine's runtime configuration.
- **Lifecycle:** authored with the machine configuration consumed by the daemon. The daemon reads it before service-loop registration; changes take effect on the next daemon configuration reload or restart.

#### Chiptunes Configuration (value object)

- **Root:** `ChiptunesConfig`
- **Contains:** `enabled` (bool, default false), `music_dir` (filesystem path to the SID corpus; defaults to the bundled `assets/audio/C64Music` location under the project root when unset), and `volume` (float).
- **Invariants:**
  - Chiptunes configuration is per-machine configuration read by the daemon.
  - `enabled=false` means the daemon plays no background music and provisions no corpus; the chiptunes worker is never spawned.
  - The HVSC SID corpus is a vendored external artifact, never tracked in version control; it is provisioned on demand into `music_dir` and is absent until provisioned.
  - Corpus provisioning is idempotent: a populated `music_dir` is left untouched, and turning `enabled` off leaves the on-disk corpus in place.
  - The corpus is provisioned from a committed manifest that pins the archive URL and its sha256; an archive whose checksum does not match the manifest is rejected rather than installed.
  - A missing or empty `music_dir` never blocks daemon startup or crashes the daemon — chiptunes degrades to silent.
  - The configuration gate `enabled` is distinct from the chiptunes manager's runtime playback state; the gate drives the runtime state, never the reverse.
- **Identifier:** the machine's runtime configuration.
- **Lifecycle:** `chiptunes` is a hot-reloadable configuration section. Toggling `enabled` is applied live by the daemon's config watcher without a restart: enabling it provisions the corpus on demand — asynchronously, so the reload never blocks — and activates playback; disabling it stops playback. The daemon never fetches the corpus synchronously at startup; when `enabled` is set and the corpus is absent, startup triggers the same idempotent asynchronous provisioning.

<!-- planned:companies-onboard -->

#### Company (aggregate)

- **Root:** `CompanyConfig`, folder-discovered under `~/.teleclaude/companies/<slug>/teleclaude.yml` (the `COMPANIES_ROOT` tree) — the company-scoped twin of the per-person tier. `extra="allow"` for additive growth.
- **Contains (v1):** `name` (display), `slug` (the company ID = folder name), `git` (the org's host/org, e.g. `github.com/InstruktAI`), `description` (one-line summary — the substance of the injected company header), `erp_id` (the single connection to the company's ERPNext record), `owner` (the leading person, referenced by `PersonConfig.slug`). A company-level `.env` in the same folder holds service credentials.
- **Invariants:**
  - The company tier is its own scope: a dedicated model + folder-discovery loader. Company fields are NOT folded into `ProjectConfig`, and no existing config is promoted into a shared multi-level model.
  - `CompanyConfig` composes into the effective configuration **alongside** `project` (both present at once) — resolved from the active project's `company:` field, NOT from workspace type (unlike person/project, which are mutually exclusive by workspace).
  - A company declares **no** domains; domain consumption scoping stays at `ProjectConfig.business.domains`. A company is not an event-domain subscriber.
  - ERP is the system of record; every "real" company detail resolves through `erp_id` and is never duplicated here. The profile is thin context-scaffolding.
  - Discovery is by folder structure only (`COMPANIES_ROOT` is the registry); there is no separate registry file.
  - Company credentials are read through one resolver seam — `load_company_credentials(slug)` — reading the company-folder `.env` (mode `0600`, **unprefixed** keys; the directory is the namespace) via the existing `${VAR}` mechanism; the seam is swappable to a secrets service without touching call sites. No new env var locates a company.
- **Identifier:** the company `slug` (folder name).
- **Lifecycle:** scaffolded and populated by `telec companies onboard` (see the company-scaffolding spec); read into the effective config when a project declares membership; read by the hook receiver to inject the company header and by project setup to derive a project's git remote.

#### Project company membership (value object)

- **Root:** `ProjectConfig.company` — an optional, kebab-case, validated, at-most-one company slug, assigned at onboarding when the project sits under a company umbrella.
- **Invariants:**
  - It is the **single determinant of the project's company context**: it both scopes which company's doc snippets surface to the project AND selects the company profile injected into the project's sessions. A project belongs to exactly one company.
  - Absent or unknown company → the project sees no company snippets and no company header is injected; the misconfiguration surfaces rather than leaking another company's data.
- **Identifier:** the project (`project_path`).
- **Lifecycle:** authored on the project overlay; resolved at config composition and at the session-start hook.

#### Person company membership (value object)

- **Root:** a `companies` set on the person overlay (`PersonConfig`), referencing company slugs.
- **Invariants:**
  - Many-to-many: one person may work for multiple companies; the value is a set, not a single slug.
  - It is an **identity record only** — it does NOT select the company injected into a session (the project does). A person in several companies cannot disambiguate the session's company on their own.
- **Identifier:** the person (`PersonConfig.slug`).
- **Lifecycle:** authored on the person overlay and surfaced in the People config (TUI People tab); not read by the session-start company injection.

<!-- /planned:companies-onboard -->

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

The v1 Python runtime does not currently emit this canonical event. Pending
`runner-dispatch`, the existing v1 config watcher/effective-config reload seam
publishes or directly bridges an equivalent wake-up for workflow's lifecycle
runner whenever an autostart-relevant key changes. The target event payload
still uses `scope`/`changed_keys`/`version`; v1 project scopes must resolve to
one canonical project path or the runner skips dispatch fail-closed.

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
- **Schema Driven Config TUI** — `docs/project/spec/feature/config/schema-driven-config-tui.md` — The config wizard renders typed config fields from canonical schemas and source-aware persistence metadata instead of TUI-local shadow models and fixed field maps. Covers machine, global, project, per-person, and env-backed config surfaces.
- **Runtime TTS Toggle** — `docs/project/spec/feature/config/runtime-tts-toggle.md` — `RuntimeSettings` is a separate mutable layer persisted as JSON with debounced (0.5s) writes; only `tts.enabled` is mutable today; `parse_patch` strictly rejects unknown keys and non-bool values.
- **Setup Wizard** — `docs/project/spec/feature/config/setup-wizard.md` — `telec config wizard` is the canonical single TeleClaude-owned interactive surface for every persisted setup value. Guarantees: single setup surface, idempotent re-runs, secret hygiene, partial-resume, at-a-glance status, release-channel + permissions/preflight coverage. Pending delivery of `simplify-install-flow-cleanup` + `install-wizard-enrichment`.
- **Machine Config Write** — `docs/project/spec/feature/config/machine-config-write.md` — `save_machine_config` mirrors `save_project_config`'s atomic-replace contract for the dataclass-backed machine `config.yml`. Sanctioned write path for machine-level config; v1 does not emit `config.effective.updated` from this writer. Delivered by `dynamic-config-tui`.
- **Atomic Env File Write** — `docs/project/spec/feature/config/atomic-env-file-write.md` — `set_env_var` is promoted from `target.write_text(...)` to the tmp-file + flush+fsync + `os.replace` pattern so the wizard's per-section atomic-write contract holds uniformly across YAML, machine config, and `.env` surfaces. Delivered by `dynamic-config-tui`.

- **Writer-contract delivery-ownership update** — `dynamic-config-tui` closes the live writer-contract gap for both **Machine Config Write** and **Atomic Env File Write** above. `dynamic-config-tui` provides the sanctioned atomic machine-config writer and promotes the env-file writer to the tmp+flush+fsync+`os.replace` pattern, so its schema-driven persistence routes only through contract-honoring writers.
- **Agent Env Allow List** — `docs/project/spec/feature/config/agent-env-allow-list.md` — `GlobalConfig.env_allow_list` and `ProjectConfig.env_allow_list` form the user-configurable authorization surface for ambient environment variables entering agent tmux sessions. Global entries cover local agent skills across projects; project entries add repository-specific names. The regular project `.env` remains application/runtime input; agent access requires listing each variable name explicitly.

### Context map position

- **Open Host Service to every domain context** — config exposes the effective configuration via a stable read interface. Every other service reads what it needs at startup and on `config.effective.updated`. Config does not know its consumers; consumers know what configuration keys they need.
- **No upstream contexts** — config is a spine context with no dependencies on other domain services. It reads from the filesystem only.
- **Anti-corruption layer with v1 (during migration)** — v1 `teleclaude/config/` module shape (Pydantic models) is preserved by the v2 shim during the migration window. The ACL converts the v2 Rust struct into the v1 Pydantic shape so existing consumers don't need code changes. ACL lives at `crates/config/src/v1_compat.rs` (planned). Disappears when `v2-config-cutover` lands.

## Allowed values

- `release_channel`: `alpha`, `beta`, `stable`.
- `workflow.runner`: `autostart`, `manual` (default `autostart`).
- `overlay_scope` (in `config.effective.updated` payload): `global`, `project:<path>`, `person:<name>`, `runtime`.

## Known caveats

- Config persistence is filesystem-first. Postgres is OPTIONAL (`effective_config_snapshots` table) and only used if effective-config history must be queryable across time. Until that use case surfaces, the service is stateless and config "lives" in YAML.
- The `~30+ consumer surface` in v1 is the broadest of any service. The v2 shim's job is to keep that surface byte-stable during migration; consumer code changes happen gradually, not as part of the cutover.
- v1 `teleclaude/config/_remote_computers.py` is being retired entirely (per the `fleet-redis-discovery` inheritance in `v2-agent-runtime`); fleet topology moves out of config and into Redis self-advertisement. The schema field `remote_computers` is dropped.
- v1 `DeploymentConfig` was misplaced on `ProjectConfig`. The v2-config-cutover relocates it to runtime config (see the cutover input). Until the cutover lands, the misplacement persists.
- Validation is schema-driven, not freeform. Adding a new config field requires updating the schema in the same PR as the consumer that reads it. Unknown keys log a warning today; v2 may tighten to errors.
