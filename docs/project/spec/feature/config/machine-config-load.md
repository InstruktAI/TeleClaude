---
description: 'Machine config load — reads `config.yml` (with env-var expansion and optional `experiments.yml` side-file), deep-merges over built-in defaults, and builds the typed runtime config aggregate at process start.'
visibility: 'public'
---

# Machine Config Load — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The runtime configuration surface (`config.yml`) is the single per-machine
file that tells the runtime and the CLI surface who the computer is, which
agents are installed, where Redis is, which Discord/Telegram credentials
apply, and which remote computers are reachable. The config bounded context
loads this file once at process start, validates raw operator input against
parser-owned accepted-key shapes before default merge and typed construction,
expands `${ENV_VAR}` references using the shell environment (after `.env` is
sourced), optionally merges a sibling `experiments.yml` for feature-flag
entries, and produces the typed runtime configuration aggregate exposed to
consumers. Undeclared keys fail with dotted paths; parser-declared aliases,
dynamic named mappings, lists, and explicitly open parameter bags remain
valid. This is the machine-level inventory layer; it is distinct from the
`teleclaude.yml` layered-overlay system that resolves per-workspace
global/project/person settings.

## Canonical fields

### Use cases

#### UC-CFG-LOAD-1: Default config.yml path is the machine home

```
When the machine config loads at process start
Then _config_path resolves to <RuntimeConfig.home>/config.yml, which defaults to ~/.teleclaude/config.yml
And the current working directory does not participate in the resolution
And no environment variable re-points that path; moving TELECLAUDE_HOME is the only way to move it
And the file is opened and parsed as YAML
And the resulting Config object is bound to the module-level `config` global
And the module-level `config_path` global is set to the absolute path
```

#### UC-CFG-LOAD-1b: The bundled blueprint seeds and backfills the machine config

#### UC-CFG-LOAD-10: Installation produces a machine configuration from the schema

```
Given a host carrying no machine configuration at <RuntimeConfig.home>/config.yml
When installation runs
Then the machine configuration is produced from the configuration schema
And each field declared sensitive is written as its derived environment reference
And no field's resolved secret value is written
```

#### UC-CFG-LOAD-11: Installation leaves an existing machine configuration alone

```
Given a host already carrying a machine configuration at <RuntimeConfig.home>/config.yml
When installation runs
Then that configuration is left byte-for-byte unchanged
And no field is added, removed, or re-derived from the schema
```

#### UC-CFG-LOAD-13: Installation can load generation before runtime configuration exists

```gherkin
Given a host carrying no machine configuration at <RuntimeConfig.home>/config.yml
When an installation agent loads the config-owned generation contract
Then loading that contract neither reads nor creates the machine configuration
And the agent can explicitly create the machine configuration through that contract
But a runtime consumer requesting the effective configuration still fails fast while the file is absent
```

#### UC-CFG-LOAD-3: Missing config.yml is a fail-fast import error

#### UC-CFG-LOAD-14: Missing machine configuration fails runtime aggregate access

```gherkin
Given the machine configuration does not exist at <RuntimeConfig.home>/config.yml
When a runtime consumer requests the effective machine configuration outside installation
Then the request fails fast with a diagnostic naming the missing file and the creation surface
And no effective configuration aggregate is bound
```

#### UC-CFG-LOAD-4: Environment variables in YAML values are expanded

```
Given config.yml contains a value like "${DISCORD_TOKEN}" or "${REDIS_URL:-redis://localhost:6379}"
And .env at <_project_root>/.env has been sourced via load_dotenv
When the machine config loads
Then env-var expansion walks the parsed YAML dict and substitutes each ${VAR} reference
And substituted values flow into the merged config used by config construction
```

#### UC-CFG-LOAD-5: Default-config values fill any gaps in user YAML

```
Given a user config.yml that omits keys such as redis.password, terminal.strip_ansi, or event_reliability.max_attempts
When the user config is deep-merged onto the default config
Then keys absent in the user file inherit the default-config value at every nesting level
And keys present in the user file override the default scalar
And mappings recurse: nested dicts are merged key-by-key, not replaced wholesale
And the merged dict is passed to config construction to build the typed runtime config aggregate
```

#### UC-CFG-LOAD-6: experiments.yml side-file appends to experiments list

```
Given config.yml is at <dir>/config.yml
And <dir>/experiments.yml exists and parses to a dict with an "experiments" key holding a list
When the machine config loads the experiments side-file after the primary config
Then env-var expansion runs against the experiments file too
And the parsed experiments list is appended to the user config's experiments list
And the combined list is deep-merged into the experiments list
```

#### UC-CFG-LOAD-7: Empty or non-dict YAML degrades into empty user config

```
Given config.yml exists but the YAML parser returns None or a non-dict value
When the machine config loads
Then the user config is coerced to an empty mapping
And the deep-merge with the default config produces only default values
And config construction raises a validation error downstream because the required `agents` section is missing
```

#### UC-CFG-LOAD-8: Env-backed credentials remain file-declared and service-available

```gherkin
Given the configuration schema declares a service credential or externally supplied service identifier sensitive, and the machine configuration carries its derived environment reference
And the referenced value exists in the runtime secret environment
When the runtime loads configuration and starts the configured service
Then the typed effective configuration contains the resolved value
And the service is available using that effective configuration
And the machine configuration retains the placeholder rather than the resolved secret
And changing the process environment after configuration loading does not bypass the effective configuration
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
Given a human operator changes only a live-reloadable machine setting while TeleClaude is running
When the running service processes the changed machine configuration
Then the next behavior governed by that setting uses the changed value
And the daemon process remains running without a restart
```


### Cross-context references

- The config bounded context does not emit the `config.effective.updated`
  event described in `project/spec/domain/config.md` for machine-config
  load. The initial machine config is read once at process start. While the
  runtime is up, the config bounded context watches the file for changes
  and hot-reloads the live aggregate in place (or self-restarts for
  connection-bound sections) — see the hot-reload note in "Known caveats" —
  but no domain event is emitted; consumers observe the mutated aggregate
  directly.
- Consumed transitively by every bounded context that reads runtime
  configuration — the runtime, the CLI surface, transport adapters
  (Telegram, Discord, WhatsApp), the agent runtime, the identity context
  (for credentials), and remote-execution paths.
- The optional `experiments.yml` side-file feeds the experiments list,
  consumed at runtime startup and by the experiment resolver — see
  `experiment-matching.md` for resolution rules.
- The `config` bounded context (`project/spec/domain/config.md`) carries
  the overlay-computation and cache-invalidation event model. Until that
  model is fully realised, `config.yml` and the `teleclaude.yml` overlays
  (see `layered-overlay-resolution.md`) coexist as two unrelated
  configuration mechanisms.

## Known caveats

- **Stored-file migration and candidate validation are distinct.** Legacy
  content owned by the config context is migrated and persisted before the
  file reaches raw input validation, on initial load and reload. A retired
  field whose destination belongs to another bounded context is instead
  projected out of the current-schema runtime view while its committed source
  remains intact. The destination owner durably imports the value before it
  invokes config-owned cleanup; reload repeats the projection, unrelated
  mutations preserve the retained source, and raw edit candidates receive
  current-schema validation without either migration path. The local
  config-owned migration contract is specified by
  `project/spec/feature/config/unknown-key-warning`.

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
  in-process watcher owns the decision.
- **Accepted keys are parser-owned.** The machine loader rejects undeclared
  keys before default merge. Each parser declares its accepted aliases,
  dynamic named mappings, list-entry shapes, and intentionally open parameter
  bags; runtime aggregate fields, defaults, templates, and existing fleet files
  do not expand the accepted input vocabulary.

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
