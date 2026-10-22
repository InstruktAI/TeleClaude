---
description: 'Machine config load — reads `config.yml` (with env-var expansion and optional `experiments.yml` side-file), deep-merges over built-in defaults, and builds the typed runtime config aggregate at process start.'
visibility: 'public'
---

# Machine Config Load — Spec

## Required reads

- @docs/local/spec/domain/config.md

## What it is

The runtime configuration surface (`config.yml`) is the single per-machine
file that tells the runtime and the CLI surface who the computer is, which
agents are installed, where Redis is, which Discord/Telegram credentials
apply, and which remote computers are reachable. The config bounded context
loads this file once at process start, expands `${ENV_VAR}` references using
the shell environment (after `.env` is sourced), optionally merges a sibling
`experiments.yml` for feature-flag entries, merges the result over the built-in
defaults, and validates it through the closed Pydantic models of the typed
runtime configuration aggregate it exposes to consumers. Undeclared keys fail
with dotted paths; section-declared aliases, dynamic named mappings, lists, and
explicitly open parameter bags remain valid. A machine schema rejection retains
the same schema-error detail as the file-backed `teleclaude.yml` overlays inside
the raised configuration-load error. Diagnostic rendering depends on the
calling surface. This is the machine-level inventory layer; it is distinct from the
`teleclaude.yml` layered-overlay system that resolves per-workspace
global/project/person settings.

A machine configuration may declare `kind: computer`. The declaration is an
address, not a setting: the loader accepts it, removes it before typed
construction, and refuses a machine configuration declaring any other kind.
It does not make the machine file an overlay tier or a context root, and a
machine configuration without the declaration loads unchanged.

Every stored machine configuration comes to declare `kind: computer`.
Installation creates a new machine configuration declared, and a stored one
without the declaration gains it through the configuration migration list
(`local/projects/teleclaude/spec/feature/config/document-migration`). A load supplies the absent
declaration in memory and writes nothing.

Installation may load the schema-derived generation contract before this file
exists; that load creates no file. Installation explicitly generates the
configuration, while runtime access to effective settings fails if the file is
still absent.

## Canonical fields

The typed aggregate exposes configuration-owned applicability and availability
for its consumers under
`local/projects/teleclaude/spec/feature/config/runtime-applicability`.

### Use cases

#### UC-CFG-LOAD-16: A declared computer kind is an address, not a setting

#### UC-CFG-LOAD-15: A stored machine configuration gains its declared kind

#### UC-CFG-LOAD-1: Default config.yml path is the machine home

#### UC-CFG-LOAD-1b: The bundled blueprint seeds and backfills the machine config

#### UC-CFG-LOAD-10: An operator installs without manually creating machine configuration

```
Given an operator installs TeleClaude on a host carrying no machine configuration at <RuntimeConfig.home>/config.yml
When installation runs
Then the machine configuration is produced from the configuration schema
And it declares the computer kind
And each field declared sensitive is written as its derived environment reference
And no field's resolved secret value is written
```

#### UC-CFG-LOAD-11: An operator upgrades without losing existing machine configuration

```
Given an operator upgrades TeleClaude on a host already carrying a machine configuration at <RuntimeConfig.home>/config.yml
When installation runs
Then that configuration is not regenerated from the schema
And the configuration migrations it has not yet passed are applied to it
```

#### UC-CFG-LOAD-13: Installation can load generation before runtime configuration exists

#### UC-CFG-LOAD-3: Missing config.yml is a fail-fast import error

#### UC-CFG-LOAD-14: Missing machine configuration fails runtime aggregate access

#### UC-CFG-LOAD-4: Environment variables in YAML values are expanded

#### UC-CFG-LOAD-5: Default-config values fill any gaps in user YAML

#### UC-CFG-LOAD-6: experiments.yml side-file appends to experiments list

#### UC-CFG-LOAD-7: Empty or non-dict YAML degrades into empty user config

#### UC-CFG-LOAD-8: An operator configures a service without storing its secret

```gherkin
Scenario: Start a service with its environment-backed setting
  Given an operator declares an environment reference for a sensitive service setting
  And the referenced value is available to the runtime
  When TeleClaude loads the configuration and starts the service
  Then the service uses the resolved value
  And the configured service is available
  And the machine configuration retains the reference instead of the secret
  And later environment changes do not bypass the loaded configuration
```

#### UC-CFG-LOAD-9: Machine configuration governs runtime settings

```gherkin
Given a human operator has either declared an exposed runtime setting in machine configuration or left it unset
When TeleClaude starts behavior governed by that setting
Then a declared setting uses the machine-configured value
And an undeclared setting preserves the built-in runtime behavior
And ambient process environment values cannot override the selected value
```

#### UC-CFG-LOAD-12: A live-reloadable machine change applies without restarting the daemon

```gherkin
Scenario: Apply a live-reloadable machine change
  Given a human operator changes a live-reloadable machine setting while TeleClaude is running
  When the running service processes the changed configuration
  Then the next behavior governed by that setting uses the changed value
  And the daemon process remains running without a restart

Scenario: Keep the last working settings after an invalid change
  Given TeleClaude is running on a machine configuration that loads
  When an operator changes the configuration so it no longer loads
  Then the running service keeps the configuration it was running on
  And `teleclaude.config.validation.failed` is reported once with the file and failure location but no configuration values
  And a start or restart is refused with the same finding while a running service stays running

Scenario: Apply a corrected live change
  Given a previous machine configuration change was refused as invalid
  When the operator corrects the configuration
  Then the new settings are applied
  And `teleclaude.config.validation.recovered` is reported
```

#### UC-CFG-LOAD-17: An operator can diagnose invalid machine settings without exposing secrets

```gherkin
Given an operator's machine configuration contains schema-invalid values
When they validate the configuration
Then the error identifies the configuration file and invalid field paths
And sensitive values and undeclared keys are masked
```

#### UC-CFG-LOAD-18: A machine configuration change that does not load is refused, not applied

### Cross-context references

- Initial machine-config loading emits no effective-update event. The running
  file watcher publishes `teleclaude.config.effective.updated` after a valid
  changed aggregate is reloaded and before its refresh/restart decision.
  That notice is separate from the file writer's commit and supplies no atomic
  source-to-event handover
  (`local/projects/teleclaude/design/architecture/event-delivery`).
- Consumed transitively by every bounded context that reads runtime
  configuration — the runtime, the CLI surface, transport adapters
  (Telegram, Discord, WhatsApp), the agent runtime, the identity context
  (for credentials), and remote-execution paths.
- The optional `experiments.yml` side-file feeds the experiments list,
  consumed at runtime startup and by the experiment resolver — see
  `experiment-matching.md` for resolution rules.
- The `config` bounded context (`local/projects/teleclaude/spec/domain/config.md`) carries
  the overlay-computation and cache-invalidation event model. Until that
  model is fully realised, `config.yml` and the `teleclaude.yml` overlays
  (see `layered-overlay-resolution.md`) coexist as two unrelated
  configuration mechanisms.

## Known caveats

- **Schema detail and diagnostic rendering are distinct.** The machine-schema
  result from `telec config validate` renders the raised error text, including
  retained non-sensitive input in schema-error detail. Its computer-readiness
  findings instead use the config-owned value-free description. Handled
  computer-patch refusals follow
  `local/projects/teleclaude/spec/feature/config/machine-config-cli-surface`;
  service start/restart refusals follow UC-CFG-LOAD-18. Those refusal descriptions
  identify the file and findings without rejected input values.

- **A null computer name is not an assigned identity.** An explicit null
  `computer.name` becomes the string `"None"` through runtime text coercion,
  while the declared configuration view reports the stored null. Schema-based
  generation can emit that null when no name default is available. Successful
  startup and health checks therefore do not establish that a computer has an
  assigned name.

- **Stored-file migration and candidate validation are distinct.** On initial
  load and reload, the stored document is brought to the current shape in
  memory by the configuration migration list before it reaches raw input
  validation, and the load never writes it
  (`local/projects/teleclaude/spec/feature/config/document-migration`). A retired field whose
  destination belongs to another bounded context leaves the view the same way;
  a migration run stores the document only after delivering that value to its
  config-owned hand-off, from which the destination owner imports it. Raw edit
  candidates receive current-schema validation without migration.

- **Process-start side effects.** The load runs once at process start with no
  opt-out. The initialisation reads files from disk, may fail with a missing
  or malformed file, and binds the runtime configuration aggregate. There is no
  redirect seam: the path is `<TELECLAUDE_HOME>/config.yml`, so pointing the load
  at a different file means relocating `TELECLAUDE_HOME` before the package is
  imported.

- **Hot reload via the config bounded context's watcher.** The process-start
  load is still one-shot, but the running runtime owns an in-process config
  watcher that watches `config.yml`, `experiments.yml`, and `.env` (debounced
  mtime poll). On a change it re-reads from disk and mutates the live
  configuration aggregate in place. Hot-reloadable sections (`summarizer`,
  `stt`, `tts`) take effect immediately — `tts` additionally re-initialises
  the TTS context. Any other changed section triggers a graceful shutdown
  request; the process supervisor relaunches the runtime, which reads the
  fresh config at startup. The supervisor's file-watch entry is gone; the
  in-process watcher owns the decision. A change that does not load is never
  applied and never triggers that restart: the running configuration stays in
  force and the refusal is reported as UC-CFG-LOAD-18 states. The tier
  declarations the service watches are judged the same way when they change, and
  report the same events per document.
- **Accepted keys are section-owned.** The closed section models reject
  undeclared keys, including a key whose value is an unresolved environment
  reference. Each section declares its accepted aliases, dynamic named
  mappings, list-entry shapes, and intentionally open parameter bags; runtime
  aggregate fields the platform derives, defaults, templates, and existing
  fleet files do not expand the accepted input vocabulary.

- **`experiments.yml` is positional, not declared.** The side-file is read
  from the same directory as the resolved `config.yml`. Neither file has an
  env-var override of its own: the side-file sits beside
  `<TELECLAUDE_HOME>/config.yml` and moves only when `TELECLAUDE_HOME` does.

- **Non-dict YAML degrades to empty.** A `config.yml` whose top level is a
  list or scalar is silently coerced to an empty mapping. The downstream
  `agents` requirement then raises, but the failure surfaces later than the
  actual cause.

- **`.env` loading is unconditional.** The env-file load runs even when the
  file does not exist (no-op in that case). The file is the project `.env` at
  the repository root, and there is no signal that it was missing.
