---
id: 'project/spec/feature/config/setup-wizard'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'target'
delivered_by:
  - 'simplify-install-flow-cleanup'
  - 'install-wizard-enrichment'
description: 'Interactive, idempotent guided walkthrough that is the single TeleClaude-owned surface for completing machine-wide setup — covers every persisted configuration value, resumes from partial state, and shows at-a-glance status before and after each pass.'
---

# Setup Wizard — Spec

## Required reads

- @docs/project/spec/domain/config.md
- @docs/project/spec/teleclaude-config.md

## What it is

The setup wizard (`telec config wizard`) is the single TeleClaude-owned
interactive surface where a human completes machine-wide setup. It is the
guided experience the human sees after `make install` and before
`make start` on a fresh machine, and the same surface they re-open later to
inspect or change configuration without leaving the TeleClaude CLI.

The wizard owns every persisted value TeleClaude needs to come up cleanly:
system identity (computer name), platform adapters (Telegram, Discord,
AI/Voice, WhatsApp), people, notifications, environment, agent
environment access (`GlobalConfig.env_allow_list`), deployment release
channel (with the stable-pinned-minor field shown only on the `stable`
channel), and a permissions/preflight section that surfaces and
status-checks the host- and adapter-level consents that commonly block
startup. The wizard guides the human toward each external prompt; it
never escalates host permissions or replaces a prompt the external system
must own.

The user experience holds five guarantees:

1. **Single setup surface.** No other TeleClaude-owned code path asks the
   human for a TeleClaude-persisted value during normal setup. External
   prompts owned by other systems — OS permission dialogs, OAuth browser
   consent, WhatsApp QR pairing, agent CLI permission probes — are
   acceptable exceptions; the wizard guides them but does not replace
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
established adapter-tab, env-var-registry, guidance-registry, and
atomic-config-write infrastructure. Persistence flows through five
distinct surfaces (see "Persistence surfaces and writers" below):
YAML overlays are typed via Pydantic (`GlobalConfig`, `ProjectConfig`,
`PersonConfig`), the machine `config.yml` is typed via the dataclass
tree loaded by `teleclaude/config/__init__.py`, and adapter / API
credentials persist through the documented env-var registry and
env-file writer. Every persisted surface the wizard writes is documented
in `project/spec/teleclaude-config`.

## Canonical fields

### Use cases

#### UC-WIZ-1: Fresh-machine single-pass setup

```
Given a fresh machine with no TeleClaude configuration
And `make install` has completed non-interactively
When the human runs `telec config wizard`
Then the wizard opens with the at-a-glance status showing every section as `unconfigured`
And the wizard guides the human through every section in turn
  (system identity, adapters, people, notifications, environment,
   agent environment access, release channel, permissions/preflight)
And every value the human provides is written through the atomic config-write path
When the human exits the wizard with all required sections completed
And the human runs `make start`
Then the daemon comes up cleanly
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
And secrets are presented in masked form with default "keep existing"
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
And required daemon-start blockers are visually distinct from optional adapter gaps
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
Then no interactive prompt collects a TeleClaude-persisted value
When a human runs `make start` on a configured machine
Then the daemon starts without any interactive prompt
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
And the step explains that the daemon must have the value in its environment
And the wizard reminds the human that existing agent sessions must be restarted
  before newly authorized values are visible to those agents
```

### Persistence surfaces and writers

The wizard writes through five distinct persistence surfaces. The
wizard does not introduce a parallel store; every persisted value
lands in one of the five surfaces below.

| Wizard scope                                          | Persistence file                              | Typed surface                          | Writer (v1)                                                  |
| ----------------------------------------------------- | --------------------------------------------- | -------------------------------------- | ------------------------------------------------------------ |
| People, subscriptions, interests, event domains       | `~/.teleclaude/teleclaude.yml` (global YAML)  | `GlobalConfig` (Pydantic)              | `cli/config_handlers.py:save_global_config`                  |
| Per-person creds, subscriptions, interests            | `~/.teleclaude/people/<name>/teleclaude.yml`  | `PersonConfig` (Pydantic)              | `cli/config_handlers.py:save_person_config`                  |
| Project metadata, deployment release channel + pin    | `<project>/teleclaude.yml` (project YAML)     | `ProjectConfig` (Pydantic)             | `config/loader.py:save_project_config` (atomic, per `atomic-project-config-write`) |
| Agent environment allow list                          | `~/.teleclaude/teleclaude.yml` (global YAML)  | `GlobalConfig.env_allow_list`          | `cli/config_handlers.py:save_global_config`                  |
| Adapter secrets, OpenAI key, runtime env overrides    | `.env` file                                   | env-var registry (untyped)             | `cli/config_handlers.py:set_env_var` (atomic — per `atomic-env-file-write`, promoted from `target.write_text` by this delivery) |
| Computer identity, agents inventory, daemon settings  | `config.yml` (machine config)                 | `Config` dataclass tree (no Pydantic)  | `save_machine_config` (target — per `machine-config-write`)  |

YAML overlays and machine config are typed and validated; the `.env`
file path holds adapter and provider credentials and is intentionally
untyped, with semantics carried by the documented env-var registry and
`_ADAPTER_ENV_VARS`. UC-WIZ-4's secret-hygiene contract applies
uniformly across both typed and env-file persistence.

The machine-config writer (`save_machine_config`) does not exist in
v1 today — `bin/init.sh` historically used `sed` against `config.yml`.
This delivery introduces the atomic-replace helper documented in
`machine-config-write`. Module placement is `config/loader.py` for
symmetry with `save_project_config`. The plan task that adds the
computer-name wizard step is the task that adds the helper.

### v1 reload semantics

v1 wizard writes do **not** publish `config.effective.updated`. That
event is part of the v2 `config` domain contract (per
`project/spec/domain/config`) and the v1 `applies_to: v1`
`machine-config-load` and `layered-overlay-resolution` specs state v1
has no filesystem watcher and no cluster-visible config event.

Consumer reload in v1 happens through the existing semantics:

- **Daemon** — reads `config.yml` and overlay files at startup.
  Operators run `make start` / `make restart` after the wizard. The
  canonical `make install → telec config wizard → make start` path
  IS the v1 reload story.
- **CLI invocations** — re-load config at module import on each
  invocation (per `machine-config-load`). The next `telec` command
  sees the new values.
- **TUI / wizard view itself** — write-then-read for the wizard's
  rendering. Each step writes through the surface's writer; the next
  render re-derives status from the persisted file (UC-WIZ-5
  mandates this).

UX consequence: after a write that affects a running daemon (e.g.,
`config.yml: computer.name`, `config.yml: agents`, `teleclaude.yml:
notifications`), the wizard surfaces a reminder that `make restart`
is required for the daemon to pick up the change. The reminder is a
display detail; the persistent contract is that v1 reload is
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

| New guided step                | Position                                | Subtab        | Persistence                                                                                |
| ------------------------------ | --------------------------------------- | ------------- | ------------------------------------------------------------------------------------------ |
| Configure System Identity      | First (before Configure Telegram)       | `environment` | `config.yml: computer.name` via `save_machine_config` (per `machine-config-write`)         |
| Configure Agent Environment Access | After Review Environment             | `environment` | `~/.teleclaude/teleclaude.yml: env_allow_list` via `save_global_config` (per `agent-env-allow-list`) |
| Configure Release Channel      | After Review Environment (last)         | `environment` | `<project>/teleclaude.yml: deployment.{channel,pinned_minor}` via `save_project_config`    |

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

| Check                                          | Mechanism                                                                              | Verdict tier                  |
| ---------------------------------------------- | -------------------------------------------------------------------------------------- | ----------------------------- |
| Telegram required env vars set                 | env-var presence: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_USER_IDS`, `TELEGRAM_SUPERGROUP_ID`   | Required daemon-start blocker |
| `config.yml` exists and parses                 | File presence + existing dataclass loader (per `machine-config-load`)                  | Required daemon-start blocker |
| Project `teleclaude.yml` exists and validates  | File presence + existing `ProjectConfig` Pydantic validation                           | Required daemon-start blocker (when run inside a project) |
| Global `~/.teleclaude/teleclaude.yml` valid    | File presence + existing `GlobalConfig` Pydantic validation                            | Optional gap                  |
| Enabled agent CLI binaries on `PATH`           | `shutil.which(<binary>)` per agent declared `enabled: true` in `config.yml: agents`    | Required daemon-start blocker |
| `TELECLAUDE_HOME` resolves and is writable     | Path resolution via `teleclaude.paths` + `os.access(path, os.W_OK)`                    | Required daemon-start blocker |
| AI/Voice keys present (when adapter enabled)   | env-var presence: `OPENAI_API_KEY` etc.                                                | Optional adapter gap          |
| WhatsApp credentials present (when enabled)    | env-var presence (per `whatsapp-env-var-override`)                                     | Optional adapter gap          |
| Discord credentials present (when enabled)    | env-var presence: Discord env vars                                                     | Optional adapter gap          |

For each non-OK row, the section renders guidance text pointing the
human at the external system that owns the prompt (OS settings, OAuth
flow, WhatsApp QR pairing, etc.). The wizard never grants, escalates,
or modifies a host-level permission itself — UC-WIZ-8 mandates this.

Cross-context status that would require a service call (e.g., "is the
daemon currently running and healthy?") is **excluded**. The wizard's
job is preflight, not health-checking.

### Section status taxonomy

The existing `classify_adapter_status` returns `configured` /
`partial` / `unconfigured`. UC-WIZ-6 extends the taxonomy with a
fourth value:

- `invalid` — schema validation fails against the typed config
  (Pydantic for YAML overlays; dataclass-parse for `config.yml`).
  Example: release channel = `stable` with empty pinned-minor (per
  `stable-channel-pinning-rule`).

The required-vs-optional distinction surfaced in the permissions
inventory above is **computed at render time** from each section's
classification (`Required daemon-start blocker` vs `Optional gap`).
No new persisted field is introduced for this distinction; it is a
rendering concern, not a state concern.

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/config.py` — `telec config`
  dispatcher; the `wizard` subcommand opens the TUI in guided mode.
- `teleclaude/cli/tui/views/_config_constants.py` — `_SUBTABS`,
  `_GUIDED_STEPS`, adapter-tab inventory, `classify_adapter_status`
  helper.
- `teleclaude/cli/tui/views/config_editing.py` — existing TUI editing
  flows the new guided steps reuse.
- `teleclaude/cli/tui/config_components/guidance.py` —
  `GuidanceRegistry` for per-field human-facing copy.
- `teleclaude/cli/config_handlers.py` — `save_global_config`,
  `save_person_config`, `set_env_var`, `resolve_env_file_path`,
  `_ADAPTER_ENV_VARS`.
- `teleclaude/cli/config_cli.py` — `_write_env_var` (env-file
  writer); existing patterns for non-interactive env mutation.
- `teleclaude/config/loader.py` — `save_project_config` (existing
  atomic-write helper) and the location of the new
  `save_machine_config` introduced by this delivery.
- `teleclaude/config/__init__.py` — machine config loader; the
  `Config` dataclass tree the new writer targets.
- `teleclaude/config/schema.py` — Pydantic models for the YAML
  overlay surfaces (`GlobalConfig`, `ProjectConfig`, `PersonConfig`).

### Cross-context references

- `project/spec/teleclaude-config` is the authoritative surface for the
  config files and env vars the wizard persists. Every new persisted
  field added by a wizard step is documented there.
- `project/spec/feature/config/stable-channel-pinning-rule` is the
  validation contract UC-WIZ-7 references. The wizard surfaces the
  rule's outcome; the rule itself is invariant of the wizard.
- `project/spec/feature/config/atomic-project-config-write` is the
  persistence contract the wizard's release-channel step traverses
  (project YAML).
- `project/spec/feature/config/agent-env-allow-list` is the
  authorization contract the wizard's agent environment access step
  traverses (project YAML).
- `project/spec/feature/config/machine-config-write` is the
  persistence contract the wizard's system-identity step traverses
  (machine `config.yml`). Authored alongside this delivery; both
  specs are joint-delivered.
- `project/spec/feature/config/atomic-env-file-write` is the
  persistence contract the wizard's adapter / API-key / env-override
  steps traverse (`.env` file). The v1 `set_env_var` helper is
  promoted from `target.write_text(...)` to the atomic-replace
  pattern by this delivery so UC-WIZ-3 and UC-WIZ-5 hold uniformly
  across every persistence surface.
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
- **No MCP integration in this surface.** MCP is not part of the
  default agent surface and has no concrete supported integration
  contract yet. A future delivery may add an optional MCP section to
  this spec; until then, MCP is out of scope.
- **v1 surface only.** This spec applies to v1; the `v2-config-cutover`
  delivery migrates whatever this spec describes. The cutover may
  re-author this spec or add a v2 diff at that time.
