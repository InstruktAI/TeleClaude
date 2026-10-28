---
description: 'Interactive, idempotent guided walkthrough that is the single TeleClaude-owned surface for completing machine-wide setup — covers every persisted configuration value, resumes from partial state, and shows at-a-glance status before and after each pass.'
visibility: 'public'
---

# Setup Wizard — Spec

## Required reads

- @docs/local/spec/domain/config.md
- @docs/local/spec/teleclaude-config.md

## What it is

The setup wizard (`telec config wizard`) is the single TeleClaude-owned
interactive surface where a human completes machine-wide setup. Installation
already leaves a fresh machine startable and owned
(`local/projects/teleclaude/spec/feature/reconciliation/fresh-machine-bootstrap`).
The wizard is where its owner then adds integrations and the rest of the
machine's configuration, and the surface they re-open later to inspect or
change configuration without leaving the TeleClaude CLI.

The wizard owns every persisted value TeleClaude needs to come up cleanly:
system identity (computer name), platform adapters (Telegram, Discord,
AI/Voice, WhatsApp), people, notifications, environment, agent
environment access (the global overlay's `env_allow_list`), deployment release
channel (with the stable-pinned-minor field shown only on the `stable`
channel), and a permissions/preflight section that surfaces and
status-checks the host- and adapter-level consents that commonly block
startup. The wizard guides the human toward each external prompt; it
never escalates host permissions or replaces a prompt the external system
must own.

The user experience holds five guarantees:

1. **Single setup surface.** No other TeleClaude-owned code path asks the
   human for a TeleClaude-persisted value during normal setup, with one
   exception: installation asks a terminal operator for the machine's first
   platform administrator while no person is registered.
   External prompts owned by other systems — OS permission dialogs, OAuth
   browser consent, WhatsApp QR pairing, agent CLI permission probes — are
   also acceptable exceptions; the wizard guides them but does not replace
   them.

2. **Idempotent re-runs.** Re-opening the wizard loads the current
   persisted values as defaults, presents them masked where appropriate,
   and accepting all defaults writes nothing materially different. Only
   fields the human actively changed are persisted.

3. **Secret hygiene.** Secrets default to "keep existing" on every run.
   Replacing or clearing a stored secret requires an explicit user action;
   paging through a section never overwrites a configured secret.

4. **Partial completion + resume.** A human can exit mid-flow and return
   later. The wizard derives every section's status from the current
   persisted config — not from a parallel wizard-session store — so the
   next run reflects reality even if the prior session ended unexpectedly.

5. **At-a-glance status.** Before stepping through, the wizard shows
   overall completion plus per-section status (`configured` / `partial` /
   `unconfigured` / `invalid`) and distinguishes required daemon-start
   blockers from optional adapter incompleteness. On close, it summarises
   remaining blockers in one screen.

The wizard delegates to the existing TUI in guided mode and reuses the
established adapter-tab and atomic-config-write infrastructure, and the
schema's own sensitivity declarations in place of a separate registry.
Persistence flows through five
distinct surfaces (see "Persistence surfaces and writers" below): YAML
overlays are typed by the config bounded context's overlay schemas
(global, project, per-person), the machine `config.yml` is typed by the
runtime configuration aggregate, and adapter / API credentials persist
through the env-file writer under the environment variables the machine-config
schema's sensitivity declarations derive. Every
persisted surface the wizard writes is documented in
`local/projects/teleclaude/spec/teleclaude-config`.

## Canonical fields

### Use cases

#### UC-WIZ-1: Fresh-machine single-pass setup

```
Given a fresh machine with no TeleClaude configuration
And `make install` has completed and established the machine's first administrator
When that administrator runs `telec config wizard`
Then the wizard opens with the at-a-glance status showing the people and environment that installation settled, and every other section as `unconfigured`
And the wizard guides the human through every section in turn
  (system identity, adapters, people, notifications, environment,
   agent environment access, release channel, permissions/preflight)
And every value the human provides is written through the atomic config-write path
When the human exits the wizard with all required sections completed
And the human runs `make start`
Then the runtime comes up cleanly
And no further TeleClaude-owned interactive prompt is presented during the install→wizard→start path
```

#### UC-WIZ-2: Every legacy `bin/init.sh` question is reachable

```
Given a list of interactive questions that legacy `bin/init.sh` asked
  (computer name, Telegram bot token, Telegram user ID,
   Telegram supergroup ID, optional OpenAI API key)
When the human opens `telec config wizard`
Then each of those questions is reachable through a wizard step
And each step's default value matches the prior default
  (e.g., system identity defaults to the hostname)
And no question that was reachable in `bin/init.sh` requires the human
  to drop into shell, env files, or undocumented config paths to answer
```

#### UC-WIZ-3: Idempotent re-run accepts current values as no-op

```
Given a wizard run where every required section is `configured`
When the human re-opens `telec config wizard`
Then every section's default value is the current persisted value
And a sensitive field shows only whether it is set, never a value
When the human accepts every default without modification
And the human exits the wizard
Then the persisted config is byte-stable relative to its prior state
  (modulo whitespace and ordering already produced by the atomic-write path)
And no secret is re-prompted, regenerated, or overwritten
```

#### UC-WIZ-4: Explicit replace is required to change a stored secret

```
Given a section contains a stored secret with default "keep existing"
When the human pages through the section without taking the explicit replace action
Then the stored secret is preserved unchanged
When the human takes the explicit replace action
And provides a new value
Then the new value is persisted via the atomic config-write path
When the human takes the explicit clear action
Then the stored secret is removed from persisted config
```

#### UC-WIZ-5: Partial completion + resume from persisted state

```
Given the human is mid-wizard with sections A and B completed
And section C is in progress
When the human exits the wizard before completing section C
Then sections A and B are persisted atomically
And section C's partial input is discarded
When the human re-opens `telec config wizard` later
Then section A status is `configured` (derived from persisted config)
And section B status is `configured` (derived from persisted config)
And section C status is `unconfigured` or `partial` based on persisted config alone
And the wizard's next-action pointer directs the human to section C
And no parallel wizard-session state store is consulted for status
```

#### UC-WIZ-6: At-a-glance status renders before stepping through

```
Given the human opens `telec config wizard`
Then the entry view shows overall completion (configured count / total count)
And every section has a status label in the set
  {configured, partial, unconfigured, invalid}
And required runtime-start blockers are visually distinct from optional adapter gaps
When the human closes the wizard
Then the closing screen summarises remaining blockers in one view
And distinguishes blockers from optional gaps
```

#### UC-WIZ-7: Release channel exposes pinned-minor only on stable

```
Given a wizard step for deployment release channel
When the step renders for the first time on a fresh machine
Then the channel field's default is `stable`
And the allowed values are `alpha`, `beta`, `stable`
When the human selects channel = `alpha` or `beta`
Then the pinned-minor field is hidden or marked not-applicable
And the persisted config does not require a pinned-minor value
When the human selects channel = `stable`
Then the pinned-minor field becomes required and is shown to the human
When the human submits channel = `stable` with an empty pinned-minor
Then the wizard surfaces a validation error referencing the stable-channel-pinning rule
And the section status becomes `invalid`
And the value is not persisted
```

#### UC-WIZ-8: Permissions / preflight section guides without escalating

```
Given a permissions / preflight section in the wizard
When the section renders
Then it shows status indicators for the host- and adapter-level consents
  that commonly block daemon startup or adapter operation
And for each not-yet-granted consent, it shows guidance pointing the human
  at the external system that owns the prompt
  (OS permission dialog, OAuth browser flow, WhatsApp QR pairing,
   agent CLI permission probe)
And the wizard does not attempt to grant, escalate, or modify any
  host-level permission itself
When an external consent is granted out-of-band
And the human re-opens the wizard
Then the corresponding status indicator reflects the new state
```

#### UC-WIZ-9: Single-setup-surface contract holds across `make install` → `make start`

Note: `simplify-install-flow-cleanup` delivers the shell-side half of this contract; `install-wizard-enrichment` still owns wizard-side coverage for legacy setup prompts.

```
Given a delivery where this feature spec is `actual`
When a human runs `make install`
Then no interactive prompt collects a TeleClaude-persisted value other than the machine's first platform administrator, asked for only while no person is registered
When a human runs `make start` on a configured machine
Then the runtime starts without any interactive prompt
When a human runs `make start` on a machine missing required configuration
Then `make start` prints a single instruction line directing the human at `telec config wizard`
And no other prompt is shown
When a human runs `make start` on a machine where only an external consent is missing
  (e.g., the OS has not yet granted accessibility permission)
Then the wizard's permissions/preflight section reflects the missing consent
And the prompt to grant the consent is owned by the external system, not by TeleClaude
```

#### UC-WIZ-10: Existing wizard coverage is preserved

```
Given the existing wizard already covers
  (Telegram, Discord, AI+Voice, WhatsApp adapters; People; Notifications; Environment)
When the enriched wizard is delivered
Then every previously-working flow continues to work
And every previously-passing validation continues to pass
And no existing adapter, person, notification, or environment behavior regresses
```

#### UC-WIZ-11: Agent environment access is configurable

```
Given an agent skill or CLI integration needs an ambient environment variable
When the human opens `telec config wizard`
Then the environment section offers an agent environment allow-list step
And the step reads and writes `~/.teleclaude/teleclaude.yml: env_allow_list`
And the human can add, remove, or keep variable names without editing YAML by hand
And each entered name is validated as a shell environment variable name
And the step explains that `.env` is not an implicit agent pass-through surface
And the step explains that the runtime must have the value in its environment
And the wizard reminds the human that existing agent sessions must be restarted
  before newly authorized values are visible to those agents
```

#### UC-WIZ-12: Config forms are schema-driven

#### UC-WIZ-13: Per-person overlay config is reachable from People

#### UC-WIZ-14: `make start` fails fast when the configured Redis is unreachable

Redis is a hard runtime dependency. The daemon stays resilient to transient Redis
loss at runtime through its reconnect loop, but `make start` does not report a
healthy runtime when Redis has never connected — an unreachable Redis surfaces at
startup instead of being swallowed.

```
Given a machine where REDIS_CLUSTER_URL is configured but the Redis server is unreachable
When a human runs `make start`
Then `make start` does not report the runtime as started successfully
And it exits non-zero within a bounded startup readiness window
And it surfaces that Redis is unreachable and how to remediate it
  (verify REDIS_CLUSTER_URL and that the Redis server is reachable)
And the daemon reports itself not ready while Redis has never connected
When the configured Redis later becomes reachable
Then the daemon reports itself ready without requiring a restart
```

#### UC-WIZ-15: Personal MCP secrets are managed from People

### Persistence surfaces and writers

The wizard writes through six distinct persistence surfaces. The
wizard does not introduce a parallel store; every persisted value
lands in one of the six surfaces below.

| Wizard scope                                          | Persistence file                             | Typed surface                                      | Writer                                                                |
| ----------------------------------------------------- | -------------------------------------------- | -------------------------------------------------- | --------------------------------------------------------------------- |
| People, subscriptions, interests                      | `~/.teleclaude/teleclaude.yml` (global YAML) | global overlay schema                              | global-config writer (config bounded context)                         |
| Per-person creds, subscriptions, interests, settings  | `~/.teleclaude/people/<slug>/teleclaude.yml` | per-person overlay schema                          | per-person-config writer (config bounded context)                     |
| Per-person MCP service secrets                        | `~/.teleclaude/people/<slug>/.env`           | MCP registry-derived secret requirements (untyped) | person-secret writer (config bounded context)                         |
| Project metadata, deployment release channel + pin    | `<project>/teleclaude.yml` (project YAML)    | project overlay schema                             | project-config writer (atomic — per `atomic-project-config-write.md`) |
| Agent environment allow list                          | `~/.teleclaude/teleclaude.yml` (global YAML) | global overlay schema (`env_allow_list`)           | global-config writer (config bounded context)                         |
| Machine-config secrets and external identifiers       | `.env` file                                  | machine-config sensitivity descriptors             | env-file writer (atomic — per `atomic-env-file-write.md`)             |
| Computer identity, agents inventory, runtime settings | `config.yml` (machine config)                | runtime configuration aggregate                    | machine-config writer (per `machine-config-write.md`)                 |

YAML overlays and machine config are typed and validated; the `.env`
file path holds adapter and provider credentials and is intentionally
untyped, with semantics carried by the machine-config schema's sensitivity
declarations and the variable names they derive. UC-WIZ-4's secret-hygiene contract applies
uniformly across both typed and env-file persistence.

The machine-config writer does not exist today — `bin/init.sh`
historically mutated `config.yml` line-by-line. This delivery
introduces the atomic-replace helper documented in
`machine-config-write.md`, placed alongside the project-config writer
in the config bounded context for symmetry. The plan task that adds
the computer-name wizard step is the task that adds the writer.

### Reload semantics

Wizard writes do **not** publish the effective-configuration-updated event. That
event is part of the `config` bounded context's domain contract (per
`local/projects/teleclaude/spec/domain/config.md`); the current machine-config-load and
layered-overlay-resolution contracts have no filesystem watcher and
no cluster-visible config event.

Consumer reload happens through the existing semantics:

- **Runtime** — reads `config.yml` and overlay files at process start.
  Operators run `make start` / `make restart` after the wizard. The
  canonical `make install → telec config wizard → make start` path
  IS the reload story.
- **CLI invocations** — re-load config at process start on each
  invocation (per `machine-config-load.md`). The next `telec` command
  sees the new values.
- **TUI / wizard view itself** — write-then-read for the wizard's
  rendering. Each step writes through the surface's writer; the next
  render re-derives status from the persisted file (UC-WIZ-5
  mandates this).

UX consequence: after a write that affects a running runtime (e.g.,
`config.yml: computer.name`, `config.yml: agents`,
`teleclaude.yml: notifications`), the wizard surfaces a reminder that
`make restart` is required for the runtime to pick up the change. The
reminder is a display detail; the persistent contract is that reload is
restart-driven, not event-driven.

### Wizard step inventory and placement

The wizard reuses the existing `_SUBTABS = ("adapters", "people",
"notifications", "environment")` set; no new subtab is added. The
`environment` subtab is broadened in scope from "env-vars-only" to
"machine-level config" so it can host machine-config fields
(computer identity, release channel) alongside env vars.

Permissions/preflight is **not** a subtab and **not** a guided step.
It is rendered as an at-a-glance status section on the entry/summary
view alongside the existing completion summary (UC-WIZ-6 is the
behavioural anchor).

`_GUIDED_STEPS` is extended with two new entries relative to the
existing seven (Configure Telegram → Configure Discord → Configure
AI + Voice → Configure WhatsApp → Review People → Review
Notifications → Review Environment):

| New guided step                    | Position                          | Subtab        | Persistence                                                                                          |
| ---------------------------------- | --------------------------------- | ------------- | ---------------------------------------------------------------------------------------------------- |
| Configure System Identity          | First (before Configure Telegram) | `environment` | `config.yml: computer.name` via the machine-config writer (per `machine-config-write.md`)            |
| Configure Agent Environment Access | After Review Environment          | `environment` | global `teleclaude.yml: env_allow_list` via the global-config writer (per `agent-env-allow-list.md`) |
| Configure Release Channel          | After Review Environment (last)   | `environment` | project `teleclaude.yml: deployment.{channel,pinned_minor}` via the project-config writer            |

Rationale for placement: system identity is foundational (later steps
may reference it in guidance text), so it leads. Agent environment access
belongs after the general environment review because it is a global user-owned
authorization decision for agent sessions, not a generic `.env` editor.
Release channel remains last, framing the "what daemon channel does this
machine run" question after the machine-level pass.

### Permissions / preflight check inventory

The permissions/preflight section runs **local checks only**. It does
not cross bounded-context boundaries through direct service calls. The
check inventory below uses local reads (file presence, env-var
presence, schema validation, local subprocess probes) with a
deterministic verdict per row.

| Check                                              | Mechanism                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Verdict tier                                       |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| Telegram env vars set (when applicable, enabled)   | env-var presence: `TELEGRAM_BOT_TOKEN`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | Required runtime-start blocker                     |
| `config.yml` exists and parses                     | File presence + machine-config loader (per `machine-config-load.md`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | Required runtime-start blocker                     |
| Project `teleclaude.yml` exists and validates      | File presence + project overlay validation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | Required runtime-start blocker (when in a project) |
| Global `~/.teleclaude/teleclaude.yml` valid        | File presence + global overlay validation                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Optional gap                                       |
| Enabled agent CLI binaries on `PATH`               | Binary lookup per agent declared `enabled: true` in `config.yml: agents`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | Required runtime-start blocker                     |
| `TELECLAUDE_HOME` resolves and is writable         | Path resolution + writability check                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | Required runtime-start blocker                     |
| AI/Voice keys present (when adapter enabled)       | env-var presence: `OPENAI_API_KEY` etc.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                | Optional adapter gap                               |
| WhatsApp credentials present (when enabled)        | env/config presence: `WHATSAPP_ACCESS_TOKEN` + `phone_number_id` (Business Cloud API, per `whatsapp-env-var-override.md`)                                                                                                                                                                                                                                                                                                                                                                                                                                              | Optional adapter gap                               |
| Discord credentials present (when enabled)         | env-var presence: Discord env vars                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Optional adapter gap                               |
| Agent CLI auth / OAuth consent (per enabled agent) | Stored OAuth/account credential presence per enabled agent (the agent runtime defines the credential source): Codex → `~/.codex/auth.json`; Gemini → `~/.gemini/oauth_creds.json`; Claude → the Claude Code login credential (macOS Keychain service `Claude Code-credentials`; the CLI's own credential store on other platforms). API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`) are **not** a consent source — the agent runtime strips them from CLI subprocess env because they bypass OAuth, so their presence must not flip this row to OK. | Required runtime-start blocker (per enabled agent) |
| Agent CLI permission readiness (per enabled agent) | Bounded local subprocess probe: invoke the enabled agent binary with its configured non-interactive flags (declared on the agents inventory) and confirm it returns without blocking on an interactive permission prompt                                                                                                                                                                                                                                                                                                                                               | Required runtime-start blocker (per enabled agent) |

Applicability in a row's condition is the configuration owner's answer under
`local/projects/teleclaude/spec/feature/config/runtime-applicability`.

The two agent-CLI rows status-check the live-consent categories UC-WIZ-8
requires the section to reflect: the agent's OAuth/browser login (the stored
credential's presence flips to OK once consent is granted out-of-band,
satisfying the re-open reflection clause) and its non-interactive permission
state (subprocess probe). For each non-OK row, the section renders guidance text
pointing the human at the external system that owns the prompt (OS settings,
OAuth login, WhatsApp Business Cloud API token setup, etc.). The wizard never
grants, escalates, or modifies a host-level permission itself — UC-WIZ-8
mandates this.

**WhatsApp consent — covered by the credentials row; no QR pairing applies.**
The implemented adapter is a WhatsApp **Business Cloud API** client (Meta Graph API), authenticated by
`WHATSAPP_ACCESS_TOKEN` + `phone_number_id` (env/config). It has **no
QR/device-pairing step** — QR pairing is the Web/linked-device model this
adapter does not implement. Its locally-statusable consent surface is exactly
the credentials checked by the "WhatsApp credentials present" row above;
confirming the token is actually authorized with Meta requires a Graph API
call, which is the excluded live-reachability ("test connection") category.
UC-WIZ-8's "QR pairing" wording anticipates a future Web/linked-device
adapter; if one is ever added, its pairing artifact becomes the status source.

**Live-consent category that is not locally statusable (open).** One UC-WIZ-8
external-prompt category cannot yet be given a status indicator from a local
read; the section renders guidance only for it, recorded here so plan tasks
derive from the finalized inventory rather than inventing a mechanism:

- **OS-level permission dialogs** (e.g., macOS automation/accessibility
  grants). No portable cross-platform local probe exists. The writable-path
  rows cover the log/path consents the runtime needs; general OS grants stay
  guidance-only.

Cross-context status that would require a service call (e.g., "is the
runtime currently running and healthy?") is **excluded**. The wizard's
job is preflight, not health-checking.

### Section status taxonomy

The existing `classify_adapter_status` returns `configured` /
`partial` / `unconfigured`. UC-WIZ-6 extends the taxonomy with a
fourth value:

- `invalid` — schema validation fails against the typed config (the
  overlay schemas for YAML overlays; the runtime configuration aggregate
  for `config.yml`). Example: release channel = `stable` with empty
  pinned-minor (per `stable-channel-pinning-rule.md`).

The required-vs-optional distinction surfaced in the permissions
inventory above is **computed at render time** from each section's
classification (`Required runtime-start blocker` vs `Optional gap`).
No new persisted field is introduced for this distinction; it is a
rendering concern, not a state concern.

### Cross-context references

- The People view and every config section render from the canonical schemas
  and save to each field's owning file, per-person overlay fields and personal
  MCP secrets included
  (`local/projects/teleclaude/spec/feature/config/schema-driven-config-tui`).

- `local/projects/teleclaude/spec/teleclaude-config` is the authoritative surface for the
  config files and env vars the wizard persists. Every new persisted
  field added by a wizard step is documented there.
- `local/projects/teleclaude/spec/feature/config/stable-channel-pinning-rule` is the
  validation contract UC-WIZ-7 references. The wizard surfaces the
  rule's outcome; the rule itself is invariant of the wizard.
- `local/projects/teleclaude/spec/feature/config/atomic-project-config-write` is the
  persistence contract the wizard's release-channel step traverses
  (project YAML).
- `local/projects/teleclaude/spec/feature/config/agent-env-allow-list` is the
  authorization contract the wizard's agent environment access step
  traverses (project YAML).
- `local/projects/teleclaude/spec/feature/config/machine-config-write` is the
  persistence contract the wizard's system-identity step traverses
  (machine `config.yml`). Authored alongside this delivery; both
  specs are joint-delivered.
- `local/projects/teleclaude/spec/feature/config/atomic-env-file-write` is the
  persistence contract the wizard's adapter / API-key / env-override
  steps traverse (`.env` file). The env-file writer is promoted to the
  atomic-replace pattern by this delivery so UC-WIZ-3 and UC-WIZ-5
  hold uniformly across every persistence surface.
- The cleanup todo `simplify-install-flow-cleanup` retires the shell-layer
  interactive prompts and points missing config at the wizard so the shell-side
  half of UC-WIZ-9 holds. The wizard-side prompt coverage remains owed by
  `install-wizard-enrichment`.

## Allowed values

- Per-section status: `configured`, `partial`, `unconfigured`, `invalid`.
- Release channel: `alpha`, `beta`, `stable` (defaults to `stable`).
- Pinned-minor field visibility: shown iff channel = `stable`; required to
  be non-empty when channel = `stable`.
- Agent environment allow-list entries: shell environment variable names
  matching `^[A-Za-z_][A-Za-z0-9_]*$`.
- External-prompt categories the wizard guides but does not own: OS
  permission dialogs, OAuth browser consent, WhatsApp QR pairing, agent
  CLI permission probes.

## Known caveats

- **Owed-to-wizard list is sourced from the cleanup delivery.** The full
  list of legacy `bin/init.sh` questions that UC-WIZ-2 enumerates is
  closed only after `install-wizard-enrichment` delivers wizard-side
  coverage. Until then, the list above (computer name, Telegram bot
  token, Telegram user ID, Telegram supergroup ID, optional OpenAI key)
  reflects the retired shell prompts.
- **Status reflects persisted config, not live external state.** A
  section flagged `configured` means the persisted values are valid;
  it does not certify that an external service (e.g., a Telegram bot,
  an OAuth token issuer) is currently reachable. Live reachability is
  the optional "test connection" Could-have, not a Must.
- **Wizard is not a host service manager.** UC-WIZ-8 explicitly excludes
  permission escalation. Discovery that a host-level escalation is
  needed is a finding for the human to act on, not a wizard
  responsibility.

- **MCP integration is person-secret management only.** The wizard projects personal MCP secret requirements into the existing People view. It does not configure MCP transports, commands, tools, or runtime behavior; those remain owned by the MCP registry and lazy runtime.

- **Subject to the config-domain cutover.** The `v2-config-cutover`
  delivery migrates whatever this spec describes. The cutover may
  re-author this spec at that time.
