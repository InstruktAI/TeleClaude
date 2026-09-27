---
description: 'Authoritative surface for TeleClaude config files, daemon runtime config, and related environment variables.'
visibility: 'public'
---

# Teleclaude Config — Spec

## What it is

The Teleclaude Config surface defines how TeleClaude configuration is initialized and validated across two distinct surfaces:

1. User-facing `teleclaude.yml` files (`GlobalConfig`, `ProjectConfig`, `PersonConfig`)
2. Daemon runtime `config.yml` loaded by `teleclaude.config`
These surfaces are related but not interchangeable. Every environment variable backing a machine-config field derives from that field's path, so the config TUI's environment list for those fields follows the schema rather than a separately maintained registry. Variables outside the machine-config schema — the deployment-time home location, and requirements declared by MCP servers or by operator-authored `ungoverned_body` entries — keep their own sources and are still recorded here.

### One filename, four tiers

Configuration lives in one filename at four tiers, and each file declares
which tier it is. `GlobalConfig`, `ProjectConfig`, `PersonConfig`, and
`CompanyConfig` are separate Pydantic models: global config owns the
machine-wide keys, while the project config owns repository-local metadata and
explicitly rejects global-only keys (`people`, `ops`, `creds`,
`notifications`, `timezone`). See `teleclaude/config/schema.py` for the
authoritative model definitions.

| File              | Location                       | Model          | Owns                                                                       |
| ----------------- | ------------------------------ | -------------- | -------------------------------------------------------------------------- |
| **Global config** | `~/.teleclaude/teleclaude.yml` | `GlobalConfig` | All project keys + `people`, `subscriptions`, `interests`, `event_domains` |

| **Project config** | `<project-root>/teleclaude.yml` | `ProjectConfig` | `project_slug`, `project_name`, `frontend_root`, `business`, `jobs`, `hooks`, `channel_subscriptions`, `code`, `docs`, `agents` |

| **Per-person config** | `~/.teleclaude/people/{slug}/teleclaude.yml` | `PersonConfig` | `slug`, `creds`, `subscriptions`, `interests`, `settings` |

| **Company config** | `~/.teleclaude/companies/{slug}/teleclaude.yml` | `CompanyConfig` | `name`, `slug`, `git`, `description`, `erp_id`, `members` (folder-discovered; composed alongside `project`) |

#### Tier declaration and editor schemas

Every one of the four files carries a `kind` key naming its own tier —
`global`, `project`, `person`, or `company`. It is a declared, validated field
of each tier's model, and each model accepts only its own value, so a file
declaring another tier fails validation rather than loading as that tier.
Resolution reads this key; it never infers a tier from where the file sits. The
resolution contract is `project/spec/feature/config/tier-declaration`.

The machine runtime `config.yml` is outside this: it carries a different
filename and takes no part in tier resolution. It declares `kind: computer`,
which addresses the file and is never a tier
(`project/spec/feature/config/machine-config-load`).

One JSON Schema per tier is generated from the same models the runtime
validates against and published, with the MCP registry schema, into the
TeleClaude home. No repository carries a schema file; publication is specified
in `project/spec/feature/reconciliation/config-schema-publication`.

A file points at its schema with a `# yaml-language-server: $schema=<ref>`
modeline. The reference is relative and fixed by the file's tier alone, derived
in one place by the configuration writer (`teleclaude/config/declaration.py`),
and written on every write of the file. A home-tree file names the home's
published schemas; a project file names them through its root's machine-local
schema link (`project/spec/feature/reconciliation/project-plumbing-convergence`).
The same document therefore produces the same bytes on every machine, with no
network fetch and no machine-local path. The modeline serves the editor only:
loading reads `kind` alone, and a file whose modeline does not resolve loads
identically.

Every configuration document — each of the four tier files and the machine
`config.yml` — also carries a top-level `schema_version` integer: the document's
position in the configuration migration list. It is a declared internal field of
each tier's model and of the machine configuration's input vocabulary, removed
before the machine aggregate is built, and never an operator setting. How a
document reaches the current version, and what reads and writes it, is
`project/spec/feature/config/document-migration`.

`kind` names a file's tier. It is unrelated to the machine-config field
exposure levels described below, which govern which `config.yml` fields reach
the operator surface.

Release-channel settings (`deployment.channel`, `deployment.pinned_minor`) are not
project-level keys. They govern TeleClaude's own self-update — a machine-wide
concern — and live on the machine runtime `config.yml` (the `TeleclaudeConfig`
aggregate), marked `tier=public` (wizard exposure stays a later refinement).

### Configuration tiers — public vs internal

Machine-config fields (`config.yml` / `TeleclaudeConfig`) declare an editability
**tier** in code: `internal` (default), `public`, or `tui`.

- `internal` (default, unmarked): constants, TTLs, QoS blocks, channel
  identifiers, and runtime-derived values. Not in a generated machine
  configuration, not in the TUI, not human-editable.
- `public`: the `config.yml` surface; agents mutate it through `telec config`,
  while runtime and UI callers submit named semantic operations to the config
  context. The backing file is not an editing surface.
- `tui`: the operator-facing render set — the only tier `telec config wizard`
  renders.

A field may additionally be declared sensitive, and its environment variable is
derived from its path. A generated machine configuration carries a sensitive
field's reference rather than its value. The full rule lives in
`project/policy/config-public-surface`.

**The project config is a regular file committed to the repository.** It is never a
symlink. Replacing it with a symlink to the global config breaks validation because
`ProjectConfig.reject_disallowed_keys` rejects `people`.

## Canonical fields

### Project config keys (`ProjectConfig`)

Valid in both project and global configs.

```yaml
project_slug: string # canonical machine identity; required in project configs
project_name: string # human-readable display name
env_allow_list: list[string] # ambient env vars explicitly allowed into agent tmux sessions for this project
frontend_root: string # optional layout override: directory containing TypeScript/frontend project, relative to project root (e.g. frontend)
description: string
business:
  publishes: # domains this project owns and contributes global docs for; the union across all registered projects is the set of valid domains, and each domain has exactly one owning publisher — a second project publishing the same domain is a sync-blocking split
    - slug: string # required: the published domain
      trigger: string # required: the domain's activation trigger, rendered enriched on its Published Domains line in agent outputs; nonblank, single-line, bounded length, validated at config load — a publishes entry without a nonblank trigger fails config load, so a domain cannot be delivered undiscoverable
<!-- planned-change:job-name-identity -->
jobs: list[JobScheduleConfig] # local job declarations and subscriptions to published global jobs, identified by execution pointer; a subscription overrides any setting it carries; no name key (project/spec/feature/config/job-declaration-model)
<!-- change:job-name-identity -->
jobs: list[JobScheduleConfig] # local job declarations and subscriptions to published global jobs, each identified by its required kebab-case `name`; a subscription overrides any setting it carries except the execution pointer (project/spec/feature/config/job-declaration-model)
<!-- /planned-change:job-name-identity -->
hooks:
  inbound: mapping[string, InboundSourceConfig]
  subscriptions: list[SubscriptionConfig]
channel_subscriptions: list[ChannelSubscription]
```

The project also declares which platform capabilities it subscribes to. Each block
is optional, and an omitted block or one without an `enabled` value is
unsubscribed, so only an explicit value claims a capability
(`project/spec/feature/config/project-capability-manifest`):

```yaml
code:
  enabled: bool # the project holds code under the TeleClaude lifecycle
docs:
  enabled: bool # the project participates in the snippet pipeline
agents:
  enabled: bool # the project holds agent artifacts
```

A project also declares its checkpoint maintenance overlay under `checkpoint`, holding two
registries keyed by action id: `checkpoint.actions`, whose entries carry `run` and `evidence`
and are obligations an agent is asked to discharge, and `checkpoint.maintenance`, whose
entries carry the command that performs them and are discharged by the mechanism that runs
them. An action id belongs to exactly one of the two, across the platform base and a
project's overlay together, and a declaration claiming an id the opposite registry already
owns is rejected at validation. The declared shape, the eligibility rule that decides which
registry an action belongs in, and the binding table that maps paths to action ids are
specified in `project/design/architecture/checkpoint-system`; the overlay is authored by
config assessment rather than by hand.

These are project-level capability toggles and are unrelated to the machine
config's `agents` block, which registers the agent CLIs themselves. They are
written by config assessment from repo shape, not edited by hand, so they carry
no wizard or TUI entry — the operator changes a subscription by re-running
assessment, and the runtime reads only the written declaration. Task tracking
carries no toggle: a project holding a `teleclaude.yml` subscribes it by that fact
alone. The full contract is
`project/spec/feature/config/project-capability-manifest`.

`ProjectConfig` additionally carries an optional `company` key — `company: string`
— an at-most-one, kebab-case, validated company slug. It is the project's company
membership and determines which company's documentation the project surfaces.
It never gives a session a company or injects a company profile.
Ownership/validation is authoritative in `project/spec/domain/config`.

`PersonConfig` carries a `slug` key — `slug: string` — the declared identity
claim naming the registered person the workspace belongs to, kebab-case and
format-validated by the model. Whether the claim binds the context to that
person is resolved by the identity context against the person registry, fails
closed on unknown, ambiguous, or disagreeing claims, and is never a load-time
grant; the contract is `project/spec/feature/identity/person-context-binding`.

`ProjectConfig` alternatively carries an optional `person` key —
`person: string` — a kebab-case, validated person slug declaring a person as
the project's owner. `company` and `person` are mutually exclusive: a project
configuration declaring both is invalid and refused at the model. Declaring
neither remains valid and composes no company. A declared owner naming a
company or person that no registry knows refuses composition with a clear
result naming the unresolved owner; no partial owner state reaches consumers.
The contract is `project/spec/feature/config/project-ownership`.

`env_allow_list` is an explicit pass-through list for agent sessions. It is the
authorization/filter surface: a name not listed in the effective allow list must
not enter agent tmux sessions, even if it exists in `.env` or in the daemon
environment. At tmux session creation, TeleClaude combines the global allow list
from `~/.teleclaude/teleclaude.yml` with project additions from
`<project>/teleclaude.yml`, reads those names from the daemon process
environment, and exports only the names that are configured and present. The
values are loaded into the pane through the session's private TMPDIR env file,
not through tmux command-line `-e` arguments; that private file is a delivery
mechanism, not an authorization mechanism. The regular project `.env` remains
the source for application/runtime secrets. Those values enter agent sessions
only when their names are also listed in the effective `env_allow_list` and are
present in the daemon environment.

### Global-only keys (`GlobalConfig` adds these)

Valid **only** in `~/.teleclaude/teleclaude.yml`. Rejected by `ProjectConfig`.

```yaml
people: list[PersonEntry] # REJECTED at project level
env_allow_list: list[string] # ambient env vars explicitly allowed into all local agent tmux sessions
subscriptions: list[SubscriptionEntry]
interests: list[string]
event_domains:
  domains: mapping[string, DomainConfig]
jobs: list[JobScheduleConfig] # the registry of published jobs with their default settings; a project runs one only by subscribing to it, inside that project
```

There is no `company_profile` key on the global overlay. Company configuration is
its own folder-discovered tier (`~/.teleclaude/companies/<slug>/teleclaude.yml`;
the value-object contract lives in `project/spec/domain/config`), not a field of
this global `teleclaude.yml`.

The company config file (`~/.teleclaude/companies/<slug>/teleclaude.yml`, model
`CompanyConfig`, `extra="allow"`) owns the company-tier keys: `name`, `slug`,
`git`, `description`, `erp_id`, `members`. `members` is the company's roster:
each entry names a registered person, the company role they hold, and the
projects of this company they are assigned to. It replaces the former `owner`
key, whose relationship the administrative role now carries; `owner` and the
former per-person `companies` list are removed from the schema; no file carries either key, and a lingering one fails at load like any undeclared key
rather than retained as permissive extras. It is folder-discovered (the `COMPANIES_ROOT`
tree) and composed into the effective config alongside `project`. A
company-level `.env` in the same folder holds service credentials, read through
the `load_company_credentials(slug)` seam.

`ProjectConfig` gains an optional `company` key — a kebab-case, validated,
at-most-one company slug — which determines the company documentation the
project surfaces and never a session's company. Ownership, location, and
validation are authoritative in `project/spec/domain/config`.

The hook receiver injects a **company header** into agent session-start context —
the company-scoped twin of the human-profile header — rendered **before** the
person header, only when the session has a company: one it was created with
through `--company`, or one it carries from the session that started it. A
project's `company:` field supplies no header; a session without a company gets
none, wherever it stands.

Global `env_allow_list` is the normal place to authorize env vars needed by
global agent skills or CLI integrations. Project `env_allow_list` is additive
for repository-specific names.

### Per-person keys (`PersonConfig`)

Valid **only** in `~/.teleclaude/people/{slug}/teleclaude.yml`.

```yaml
creds:
  telegram: { user_name, user_id, chat_id }
  discord: { user_id, nick, avatar_url, voice_bot_token } # voice_bot_token is ${DISCORD_TOKEN} in the owner-only person .env and must authenticate the same bot the Discord adapter runs; the person's live private channel comes from Discord voice state and is not config
  whatsapp: { phone_number }
subscriptions: list[SubscriptionEntry]
interests: list[string]
settings:
  output_visibility:
    system_messages: null | off | mobile | full | both
    tool_calls: null | off | mobile | full | both
```

`accounts` is an additional per-person key: the list of mail accounts a person's
assistant may act as. Each entry declares the connector it belongs to, drawn from
the platform's own vocabulary (`google | microsoft`) rather than any vendor tool
name, and the address itself. The list may be empty, and a person's `email`
identity is not one of these accounts unless it also appears here. An entry
naming a connector outside that vocabulary is rejected at load.

`creds.discord.nick` is optional. When present, it is the Discord-facing display name for
reflected human input. Personal workspace resolution uses the canonical `people[].slug`;
`people[].name` is a display field, and identity/authorization resolve on `email` and `role`.

`creds.discord.avatar_url` is optional Discord-derived presentation data. Discord invitation
redemption captures the person's current Discord avatar URL beside the account binding. When
absent, no avatar lookup or third-party fallback is performed, and the person's reflected
messages retain the no-avatar behavior.

`preferred_channel` is an additional per-person key (`telegram | discord |
whatsapp | email`, default `email` when absent — the one channel every person
has by construction): the recipient-owned default
delivery channel for person-addressed messaging (`telec message`). The person's
own config file is the single source of truth for this routing default; the
per-subscription `preferred_channel` on notification subscriptions is unrelated
and scopes only that subscription's event delivery.

`invite_token` is relocated out of `PersonConfig` into ephemeral invitation
state under `~/.teleclaude/state/` — the invitation handshake is an identity
concern (binding a transport handle to a known person), not configuration. Invite generation and
Telegram/Discord redemption read and write the ephemeral invitations store
instead of scanning per-person overlays. See
`docs/project/spec/feature/config/schema-driven-config-tui.md`.


Person-bound service secrets live in `~/.teleclaude/people/{slug}/.env`, beside but separate from the typed person overlay. The `.env` file is an opaque secret store, not a `PersonConfig` field: person YAML contains no secret inventory or values. The canonical person slug selects the folder; each file is owner-only `0600` and is read or mutated only through the config bounded context's person-secret store. Secret status exposed to the config TUI contains names and requirement provenance but never values, including while a secret is being replaced. Keep performs no write; replace and clear are atomic targeted mutations that preserve every unrelated key and line in the same file.


Typed config keys are part of the interactive config surface. The config wizard
must render machine config, global overlay, project overlay, per-person overlay,
and env-backed values from their canonical schemas or registries, with view
metadata only deciding grouping and presentation. `creds`, tokens, secrets, and
settings are not excluded from the TUI because they are nested or sensitive. A
field the schema declares sensitive is set through that same surface while its
value is never rendered back.

### TeleClaude MCP registry

TeleClaude-owned MCP registries live at repo-root `teleclaude-mcp.jsonc` and
optional repo-root `teleclaude-mcp.local.jsonc`. The shared file is committed;
the local file is machine-specific and gitignored. Both are JSONC documents
whose shape — every property, its allowed values, and its default — is owned by
the MCP registry schema authored in the MCP context's source (`teleclaude/mcp/`).

`trigger` is the agent-facing activation text shown by `telec mcp list`. It is
metadata only: it does not create environment requirements or change a daemon
lease fingerprint.


A TeleClaude project's own `teleclaude-mcp.jsonc` and optional
`teleclaude-mcp.local.jsonc` at its checkout root declare project-local MCP
servers using the identical wrapper shape and schema. Project declarations are
deep-merged over the machine-wide registry for invocations from that project,
with project definitions taking precedence and the local overlay taking
precedence over the shared file within each root. The project layer reads only
these two canonical files; `mcp.json` / `mcp.local.json` compatibility imports
remain a machine-wide-root contract.

Server entries in either scope may declare `hidden`; its type and default live
in the MCP registry schema. A hidden server is excluded from index-mode listings baked
into generated agent entrypoints while remaining fully served and listed by the
runtime `telec mcp list` surface; `hidden` affects neither startup, credential
lookup, nor lease fingerprints.



`credentialScope` selects the credential owner — the machine, or the calling person; its allowed values and default live in the MCP registry schema. A person-scoped server requires authoritative caller identity and resolves every placeholder from that person's secret store. The declaration participates in normalized registry and lease fingerprints.


Registry authors omit default-valued properties; the runtime model and the
registry schema provide the defaults. The registry schema is published with the
configuration schemas
(`project/spec/feature/reconciliation/config-schema-publication`), and a
committed registry file references it relatively through its root's
machine-local schema link, so JSON Schema aware editors validate and
autocomplete it without network access and without a machine-local path.


The effective TeleClaude MCP registry is resolved per invocation scope by one
config-owned resolver. For machine-wide scope it is the nested merge of the
machine-wide `teleclaude-mcp.jsonc` and `teleclaude-mcp.local.jsonc` by server
slug, with `mcp.json` and `mcp.local.json` remaining machine-wide-only
compatibility import inputs for the transition window (native JSON
`mcpServers` shape, normalized into the TeleClaude registry model). For an
invocation from a project that declares a registry, the project's canonical
`teleclaude-mcp.jsonc` and `teleclaude-mcp.local.jsonc` are deep-merged over
that machine-wide result — machine shared → machine local → project shared →
project local, later layers taking precedence — and compatibility inputs are
never read from a project root. The installer and daemon never mutate any
input file.



Environment values in the registry are placeholders, not secrets. Any command,
args, headers, URL, or env value containing `$VAR` or `${VAR}` markers creates a
runtime environment requirement. For global scope the daemon resolves those
values from `~/.teleclaude/.env`; for person scope it resolves them exclusively
from `~/.teleclaude/people/{slug}/.env` after verified caller-to-person
resolution. The daemon passes resolved values only to the MCP child process or
remote request construction boundary. Literal `env` values without placeholders
stay literal and do not trigger secret lookup. A missing identity, person, safe
secret file, or non-empty required key fails before lease startup without
cross-scope fallback.


Managed MCP servers use TeleClaude's lazy runtime exclusively. They are exposed
to agents through `telec mcp` and `/mcp` routes; native agent MCP configs are
not a publication target. Legacy Gemini MCP settings are not managed.

### Environment variables

The credential variables below are secret-storage inputs for `${VAR}`
placeholders in machine `config.yml`. Generic YAML expansion resolves them at
config load; runtime consumers read only the resulting typed fields and never
consult the process environment directly.

```yaml
# Names backing a machine-config field derive from that field's path.
# `TELECLAUDE_HOME` is not a machine-config field and does not derive.
environment_variables:
  # Telegram adapter
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_ALERT_USERNAME
  - TELEGRAM_ALERT_CHAT_ID
  # Discord adapter
  - DISCORD_TOKEN
  - DISCORD_GUILD_ID
  - DISCORD_HELP_DESK_CHANNEL_ID
  - DISCORD_ESCALATION_CHANNEL_ID
  - DISCORD_ALL_SESSIONS_CHANNEL_ID
  # WhatsApp adapter
  - WHATSAPP_PHONE_NUMBER_ID
  - WHATSAPP_ACCESS_TOKEN
  - WHATSAPP_WEBHOOK_SECRET
  - WHATSAPP_VERIFY_TOKEN
  - WHATSAPP_TEMPLATE_NAME
  - WHATSAPP_BUSINESS_NUMBER
  # Summarizer providers; also editable in the Providers subtab (AI section)
  - SUMMARIZER_LOCAL_BASE_URL # OpenAI-compatible local summarizer endpoint (e.g. LM Studio)
  - SUMMARIZER_LOCAL_MODEL # model id loaded in the local server
  - SUMMARIZER_LOCAL_API_KEY
  - SUMMARIZER_OPENAI_MODEL
  - SUMMARIZER_OPENAI_API_KEY
  - SUMMARIZER_ANTHROPIC_MODEL
  - SUMMARIZER_ANTHROPIC_API_KEY
  - SUMMARIZER_GOOGLE_MODEL
  - SUMMARIZER_GOOGLE_API_KEY
  # Voice providers are operator-authored entries under an `ungoverned_body`;
  # their references are authored in the configuration, not derived here.
  # Redis transport — essential infrastructure. Editable in the Infra subtab (Redis section)
  # as ${VAR}-backed fields, and a mandatory guided-wizard step (the Infra step is not
  # complete until REDIS_URL is set). Also listed in the config TUI's environment section.
  - REDIS_URL
  - REDIS_PASSWORD
  # Current machine-config field with no runtime consumer.
  - DATABASE_URL
  # RuntimeConfig one-shot path control. RuntimeConfig reads this once at
  # process startup and freezes it; it is the only env var that moves a
  # TeleClaude-owned path.
  - TELECLAUDE_HOME # runtime state root override; defaults to ~/.teleclaude
  # Postgres (v2 only) — DATABASE_URL is deactivated until the v2 workflow cutover; it is
  # commented out in .env and is NOT part of make install yet.
  # Email and backup — editable in the Providers subtab, saved to .env.
  # Firecrawl is supplied by the person's own environment for MCP loading.
  - EMAIL_EMAIL_FROM
  - EMAIL_REPLY_TO
  - EMAIL_SMTP_USERNAME
  - EMAIL_SMTP_KEY
  - EMAIL_SMTP_RELAY # host:port
  - BACKUP_AWS_ACCESS_KEY_ID
  - BACKUP_AWS_SECRET_ACCESS_KEY
  - BACKUP_AWS_S3_HOST
  - BACKUP_AWS_S3_REGION
  - BACKUP_AWS_S3_BUCKET
  - BACKUP_BACKUP_PREFIX
```

`teleclaude.runtime.config` is the one-shot owner for the controlled path env
surface. It reads `TELECLAUDE_HOME` once at module import and freezes it into
`RuntimeConfig`. Runtime code reads that value through `get_runtime_config()`
rather than consulting or mutating process env later.

`TELECLAUDE_HOME` is the single anchor. It changes the root for runtime state
files such as databases, logs, global docs, commands, people configs, and
session temp directories; every other TeleClaude-owned path derives from it or
from the project root, and no second env var re-points a path it already
determines.

`teleclaude.paths` is the sole composer of those paths, and the config
filenames it composes them from — the `teleclaude.yml` overlay, the machine
`config.yml`, and `.env` — are a single closed vocabulary declared there. A
module needing one of those paths imports the constant; a module needing one of
those filenames references the vocabulary member. Neither is re-derived
locally, so every consumer resolves to one declaring node.

### Daemon runtime config keys (`config.yml`)

The daemon runtime config lives at `~/.teleclaude/config.yml` (under `TELECLAUDE_HOME`).
Installation produces the runtime file from the configuration schema when the host
carries none, writing each sensitive field as its derived environment reference. A host
that already carries a runtime file is never regenerated; installation applies the
configuration migrations the file has not yet passed
(`project/spec/feature/config/document-migration`). The TUI, daemon, and installer
read and write only the runtime
file. `make install` writes opted-in agents' `enabled`

state into the runtime file. The runtime file's path is
`<TELECLAUDE_HOME>/config.yml` with no override: moving the runtime tree moves
the config with it.

The `agents` config key for the Antigravity agent is `gemini`; its binary resolves to
`agy` via `resolve_agent_binary`. The installer heals any legacy `agy:` key back to
`gemini:` so the parser (which accepts only `claude`/`gemini`/`codex`/`deepseek`)
does not reject it. The `deepseek` agent runs DeepSeek Harness headless:
`dsh --profile dsh-tui <prompt>` (one-shot turn; `prompt_at_launch`), sessions
under `~/.dsh/sessions`. Its receiver hooks are written by `configure_dsh` to
`~/.dsh/hooks.json` with the `unsandboxed: true` opt-in, and its plugin row is
merged into the machine-local `~/.dsh/cordis.patch.yml`.

The TTS-exclusive dependencies live in the `tts` optional extra in `pyproject.toml`,
not in the core dependency set, so `make install` does not install them. They are
installed on demand the first time TTS is enabled at runtime; `config.tts.enabled`
is a boot default-intent seed, while the runtime-settings layer owns the live
enable/mute. Dependencies shared with other features — `mlx-audio` (also the STT
Parakeet backend), `openai` (also STT Whisper and the summarizer) — stay in the core
dependency set.

These keys are loaded by the daemon runtime config parser in `teleclaude/config/__init__.py`.

```yaml
computer:
  name: string
  is_master: boolean # exactly one master per fleet; gates shared Discord channel provisioning (non-master computers resolve shared channels by name, never create)
  is_ingress_node: boolean # designates this node as the cluster's single webhook ingress; gates the cluster.webhook relay (default: false)
<!-- planned:distributed-todo-postgres -->
  is_cluster_db_host: boolean # designates this node as the host of the shared cluster database (Postgres); exactly one per fleet; default false. Independent of is_master and is_ingress_node — it is its own role. Currently this is usually the ingress node by deployment convention (no secure cross-node transport yet), but that is convention, not a requirement: the host may relocate once secure inter-node transport exists.
<!-- /planned:distributed-todo-postgres -->
  user: string # remote attach identity; must match [A-Za-z0-9._-]+
  role: string
  default_working_dir: string
  timezone: string
  host: string | null # remote attach identity; must match [A-Za-z0-9._-]+ when set
  trusted_dirs: list[TrustedDir]
remote_computers:
  <name>:
    user: string | null # remote attach identity; must match [A-Za-z0-9._-]+ when set
    host: string | null # remote attach identity; must match [A-Za-z0-9._-]+ when set
    ip: string | null
    teleclaude_path: string | null
<!-- planned:distributed-todo-postgres -->
services:
  cluster_db:
    dsn: string # connection string every node uses to reach the shared cluster database (Postgres), hosted on the node with computer.is_cluster_db_host. The DSN is a secret (it may carry credentials) and follows the Redis connection precedent: config.yml carries the ${CLUSTER_DB_DSN} placeholder, the value lives in .env, and the TUI config tab's Infra subtab edits it as an env-backed secret alongside the Redis connection — the raw value is never authored in config.yml and never rendered back in full. Config validation rejects a resolved DSN whose endpoint is not loopback or a private-network (RFC1918/link-local) address — a public endpoint fails validation and the daemon refuses to start. The host binds Postgres to loopback plus the cluster's private network only and never the public interface; each node resolves the DSN to reach the host — loopback on the host itself, the host's private-network address from every other node. The todo store is the first store to use the cluster DB (more may follow); every other store stays local SQLite. Absent/unreachable → todo writes fail closed with an operator-visible error (no local fallback, no queued local write).
<!-- /planned:distributed-todo-postgres -->
telegram:
  enabled: boolean
  bot_token: string | null # normally ${TELEGRAM_BOT_TOKEN}
  alert_username: string | null # normally ${TELEGRAM_ALERT_USERNAME}
  alert_chat_id: string | null # normally ${TELEGRAM_ALERT_CHAT_ID}
discord:
  enabled: boolean
  token: string | null # sensitive; ${DISCORD_TOKEN}
  guild_id: integer | null # normally ${DISCORD_GUILD_ID}
whatsapp:
  enabled: boolean
  phone_number_id: string | null # normally ${WHATSAPP_PHONE_NUMBER_ID}
  access_token: string | null # normally ${WHATSAPP_ACCESS_TOKEN}
  webhook_secret: string | null # normally ${WHATSAPP_WEBHOOK_SECRET}
  verify_token: string | null # normally ${WHATSAPP_VERIFY_TOKEN}
  template_name: string | null # sensitive; ${WHATSAPP_TEMPLATE_NAME}
  template_language: string
  business_number: string | null # normally ${WHATSAPP_BUSINESS_NUMBER}
database_url: string | null # no current consumer; normally ${DATABASE_URL}
email:
  enabled: boolean # outbound SMTP; disabled or incomplete config is unavailable
  smtp_username: string | null # sensitive; ${EMAIL_SMTP_USERNAME}
  smtp_key: string | null # sensitive; ${EMAIL_SMTP_KEY}
  email_from: string | null # sensitive; ${EMAIL_EMAIL_FROM}
  reply_to: string | null # sensitive; ${EMAIL_REPLY_TO}
  smtp_relay: string # sensitive; ${EMAIL_SMTP_RELAY}; defaults to smtp-relay.brevo.com:587
backup:
  aws_access_key_id: string | null # sensitive; ${BACKUP_AWS_ACCESS_KEY_ID}
  aws_secret_access_key: string | null # sensitive; ${BACKUP_AWS_SECRET_ACCESS_KEY}
  aws_s3_host: string | null # sensitive; ${BACKUP_AWS_S3_HOST}
  aws_s3_region: string | null # sensitive; ${BACKUP_AWS_S3_REGION}
  aws_s3_bucket: string | null # ${BACKUP_AWS_S3_BUCKET}
  backup_prefix: string | null # sensitive; ${BACKUP_BACKUP_PREFIX}
agents:
  default: string
  claude|gemini|codex|deepseek:
    enabled: boolean
    profiles: # optional per-profile override of the platform-default launch flags; a named profile replaces that profile's flags outright, unnamed profiles keep the platform default. `restricted` is the profile every non-admin session launches under, so overriding it changes their permission posture.
      default|restricted: string
    model_chains: # optional per-mode override of the platform-default launch-model fallback chain; omitted modes keep the platform default
      fast|med|slow: # ordered list of entries in fallback order; the first entry whose model has no active model-scoped unavailability launches
        - model: string # model identity, matched against model-scoped availability records
          flags: string # complete, opaque launch flags for this entry; the platform never derives flags from a template. Startup validation rejects unknown modes and malformed entries, referencing the concrete config.yml path.
event_reliability:
  idle_threshold_ms: integer # minimum idle time before stale pending entries can be reclaimed
  max_attempts: integer # cumulative retry ceiling before dead-letter transition
  sweep_interval_ms: integer # periodic stale-pending sweep cadence
  dlq_destination: string # dead-letter destination identity
process_janitor:
  scan_interval_seconds: integer # host process-table scan cadence (default 300; floor 60)
  default_signature_ttl_seconds: integer # grace window before a matched leak signature becomes reapable (default 3600; floor 60)
  lease_ttl_seconds: integer # spawn-registry lease lifetime for platform-detached children (default 1800; floor 60)
  dry_run_default: boolean # when true, matched processes are observed and emitted but not killed (default true)
  reap_revalidation_seconds: integer # revalidation window for reap-event notification de-duplication per (pid, signature_id); repeat sightings within the window reuse the existing notification row instead of creating a new one (default 3600; floor 60)
summarizer:
  local: # OpenAI-compatible local provider (e.g. LM Studio); tried first when enabled
    enabled: boolean
    base_url: string # sensitive; ${SUMMARIZER_LOCAL_BASE_URL}
    model: string # sensitive; ${SUMMARIZER_LOCAL_MODEL}
    api_key: string | null # normally ${SUMMARIZER_LOCAL_API_KEY}
  provider_priority: list[string] # cloud fallback order: openai|anthropic|google
  openai: { model: string, api_key: string | null } # sensitive; ${SUMMARIZER_OPENAI_MODEL}, ${SUMMARIZER_OPENAI_API_KEY}
  anthropic: { model: string, api_key: string | null } # sensitive; ${SUMMARIZER_ANTHROPIC_MODEL}, ${SUMMARIZER_ANTHROPIC_API_KEY}
  google: { model: string, api_key: string | null } # sensitive; ${SUMMARIZER_GOOGLE_MODEL}, ${SUMMARIZER_GOOGLE_API_KEY}; uses Gemini's OpenAI-compatible endpoint
stt:
  enabled: boolean
  services:
    openai: { enabled: boolean, api_key: string | null } # API key normally ${OPENAI_API_KEY}
tts:
  enabled: boolean
  services:
    openai: { enabled: boolean, api_key: string | null } # API key normally ${OPENAI_API_KEY}
    elevenlabs: { enabled: boolean, api_key: string | null } # API key normally ${ELEVENLABS_API_KEY}
    <service>: { ..., voices: [{ name, voice_id? }], discord_voice: string } # discord_voice is one name from that service's own voices list; defaults to the first entry, and is absent when the service declares no voices, which keeps that service out of the room chain; a name outside the list fails validation naming the service
```

Summary/title generation tries `local` (when `enabled` + `base_url`) first, then the
cloud providers in `provider_priority`, each skipped silently when its typed
`api_key` field is absent. `local`, `openai`, and `google` share the OpenAI SDK;
`anthropic` uses its own. Empty summaries (for example, all configured providers
being unavailable) suppress agent-stop TTS and leave generic session titles.

Runtime settings owned by the machine-config aggregate use these additional
sections. Unless marked otherwise, these fields are internal: they retain the
built-in values shown here and remain absent from a generated machine
configuration and from the config TUI.

```yaml
hook_outbox:
  poll_interval_s: 1
  batch_size: 25
  lock_ttl_s: 30
  base_backoff_s: 1
  max_backoff_s: 60
  session_idle_timeout_s: 5
  session_max_pending: 32
  session_critical_reserve: 8
  session_claim_high_watermark: derived # max(1, session_max_pending - 8)
  session_claim_low_watermark: derived # max(0, session_claim_high_watermark // 3)
  summary_interval_s: 15
  backlog_warn_threshold: 20
  lag_warn_threshold_s: 3
  warn_log_interval_s: 15
  max_lag_samples: 2048
  staleness_ttl_s: 300
api:
  watch_interval_s: 5
  watch_lag_threshold_ms: 250
  watch_inflight_threshold_s: 1
  watch_dump_cooldown_s: 30
  mcp_reaper_interval_s: 30
  ws_control_send_timeout_s: 30
  ws_default_send_timeout_s: 15
  ws_replaceable_send_timeout_s: 5
daemon:
  api_restart_max: 5
  api_restart_window_s: 60
  api_restart_backoff_s: 1
  resource_snapshot_interval_s: 60
  launchd_watch_interval_s: 300
  launchd_watch_enabled: true
  startup_gate_timeout_s: 15
  startup_gate_poll_interval_s: 0.25
  agent_prompt_ready_timeout_s: 60
  log_level: INFO # tui
  legacy_gemini_root: ~/.gemini/tmp
tts:
  services:
    <mlx-service>:
      cli_bin: null
      instruct: A clear, natural conversational voice.
stt:
  services:
    parakeet:
      model: mlx-community/parakeet-tdt-0.6b-v3
      cli_bin: null
```

The service-level TTS and STT settings inherit their existing operator-facing
tiers. `daemon.log_level` is operator-facing and reaches agent-session subprocesses
as `TELECLAUDE_LOG_LEVEL` only at the subprocess environment-construction boundary,
so the git wrapper retains the same effective level without process environment
becoming runtime configuration authority.

Hook-outbox watermark normalization applies to both derived and explicitly
declared values. The high watermark is capped at `session_max_pending`; a low
watermark greater than or equal to the resolved high watermark becomes
`max(0, session_claim_high_watermark - 1)`; and the critical reserve is clamped
to the inclusive range from zero through `session_max_pending`. The high
watermark's omitted-value derivation subtracts the literal value eight and is
independent of a configured critical reserve.


Discord provider IDs are not config. `config.yml` carries only the desired setup
inputs a machine declares — `computer.name`, `computer.is_master`, the registered
`trusted_dirs` entries, `discord.enabled`, and `discord.guild_id` (the operator's
own guild identifier, never provider-returned reflection state). Category,
channel, forum, thread, and message IDs the Discord provider returns are durable
reflection records in the runtime database, and the daemon never writes them back
to `config.yml`. Project forum bindings, launcher threads, and launcher starter
messages are read from and written to that reflection state; see
`project/spec/feature/integration/discord-admin-reflection-state`.


### Maintenance

This spec must be updated whenever a documented config key or env var is added, renamed, or removed.

A variable backing a machine-config field is derived from that field's path, so no registry is kept in sync with it. Variables from other sources — the deployment-time home location, MCP server requirements, and operator-authored `ungoverned_body` entries — are still recorded here when they are added, renamed, or removed.

Daemon-only structural keys in `config.yml` must also be documented here, but they only require wizard or env-var changes when those keys become part of the interactive `teleclaude.yml` setup flow.

### Project registry

Registered project roots live in `~/.teleclaude/projects.yaml`, a root-only
registry — it stores only absolute project paths:

```yaml
projects:
  - /abs/path/to/project-a
  - /abs/path/to/project-b
```

All per-project metadata (`project_slug`, `project_name`, `jobs`, docs index
location, etc.) lives in each project's own `teleclaude.yml` and is loaded
through `ProjectCatalogService`. `telec config project init` is the sole writer of the
registry; publication never registers projects. `project_slug` is the
canonical machine identity used for the log namespace
(`instrukt-ai-logs {project_slug}`), the cross-project docs namespace, and
service-level project lookup. `project_name` remains display-only.

<!-- planned:github-todo-mirror -->

### GitHub mirror

The `github` section parameterizes the per-project GitHub todo mirror. `github.enabled`
is the per-project toggle the repo owner sets to turn the mirror on; every mirror
projection checks it before any write — it is the entire enablement decision (no
detection, probe, or prompt). The section also holds a rebuildable cache of
GitHub-generated identifiers — the Projects v2 board node id, single-select field option
ids, and an id→issue map — an accelerator only, never authoritative, reconstructible by
scanning issue `roadmap.id` markers. No credentials live in config: the mirror
authenticates through the machine's existing `gh` login (scopes `repo` + `project`).

<!-- /planned:github-todo-mirror -->

## Known caveats

- `config.yml:agents` is required; startup fails if it is missing.
- `config.yml:agents` must only contain known agent keys (`claude`, `gemini`, `codex`).
- At least one configured agent must have `enabled: true`; all-disabled configs fail startup.
- Validation errors must reference concrete `config.yml` paths to fix (for example `config.yml:agents.codex.enabled`).
- Changing a configuration key from optional to required is a breaking change (Minor bump).
- Removing or renaming a configuration key is a breaking change.
- Adding a new optional key or environment variable is a patch.

- **The project `teleclaude.yml` must be a regular file, never a symlink.** `ProjectConfig` validation rejects global-only keys like `people`. Symlinking to the global config causes runtime errors. A project-level `agents` block is the capability toggle, not the machine config's agent-CLI registry.
