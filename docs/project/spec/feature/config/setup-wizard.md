---
id: 'project/spec/feature/config/setup-wizard'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'target'
delivered_by:
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
AI/Voice, WhatsApp), people, notifications, environment, deployment
release channel (with the stable-pinned-minor field shown only on the
`stable` channel), and a permissions/preflight section that surfaces and
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
atomic-config-write infrastructure. Every persisted field the wizard
writes is part of the typed config schema documented in
`project/spec/teleclaude-config`.

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
   release channel, permissions/preflight)
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

### Implementation pointers (v1)

- `teleclaude/cli/telec/handlers/config.py` — `telec config` dispatcher;
  the `wizard` subcommand opens the TUI in guided mode.
- `teleclaude/cli/tui/views/_config_constants.py` — guided-step
  definitions, adapter-tab inventory, status classification helper.
- `teleclaude/cli/tui/config_components/guidance.py` — env-var guidance
  registry (the per-field human-facing copy surface the wizard reuses).
- `teleclaude/config/loader.py` — atomic config-write path
  (`save_project_config`) and matching load helper.
- `teleclaude/config/schema.py` — typed `GlobalConfig`, `ProjectConfig`,
  `PersonConfig` Pydantic models the wizard writes into.

### Cross-context references

- `project/spec/teleclaude-config` is the authoritative surface for the
  config files and env vars the wizard persists. Every new persisted
  field added by a wizard step is documented there.
- `project/spec/feature/config/stable-channel-pinning-rule` is the
  validation contract UC-WIZ-7 references. The wizard surfaces the
  rule's outcome; the rule itself is invariant of the wizard.
- `project/spec/feature/config/atomic-project-config-write` is the
  persistence contract every wizard step's write traverses. The wizard
  does not introduce a parallel write path.
- The cleanup todo `simplify-install-flow-cleanup` retires the
  shell-layer interactive prompts so the single-setup-surface contract
  in UC-WIZ-9 holds. That todo's "owed-to-wizard" list seeds this
  spec's UC-WIZ-2 coverage and is locked once the cleanup delivers.

## Allowed values

- Per-section status: `configured`, `partial`, `unconfigured`, `invalid`.
- Release channel: `alpha`, `beta`, `stable` (defaults to `stable`).
- Pinned-minor field visibility: shown iff channel = `stable`; required to
  be non-empty when channel = `stable`.
- External-prompt categories the wizard guides but does not own: OS
  permission dialogs, OAuth browser consent, WhatsApp QR pairing, agent
  CLI permission probes.

## Known caveats

- **Owed-to-wizard list is sourced from the cleanup delivery.** The full
  list of legacy `bin/init.sh` questions that UC-WIZ-2 enumerates is
  closed only after `simplify-install-flow-cleanup` delivers. Until
  then, the list above (computer name, Telegram bot token, Telegram
  user ID, Telegram supergroup ID, optional OpenAI key) reflects the
  current `bin/init.sh` interactive prompts.
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
