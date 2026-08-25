---
description: 'Machine config load — reads `config.yml` (with env-var expansion and optional `experiments.yml` side-file), deep-merges over built-in defaults, and builds the typed runtime config aggregate at process start.'
visibility: 'public'
---

# Machine Config Load — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

<!-- planned-change:config-schema-strictness -->
The runtime configuration surface (`config.yml`) is the single per-machine
file that tells the runtime and the CLI surface who the computer is, which
agents are installed, where Redis is, which Discord/Telegram credentials
apply, and which remote computers are reachable. The config bounded context
loads this file once at process start, deep-merges the user's YAML over a
built-in defaults mapping, expands `${ENV_VAR}` references using the shell
environment (after `.env` is sourced), optionally merges a sibling
`experiments.yml` for feature-flag entries, and produces the typed runtime
configuration aggregate exposed to consumers. This is the machine-level
inventory layer; it is distinct from the `teleclaude.yml` layered-overlay
system that resolves per-workspace global/project/person settings.
<!-- change:config-schema-strictness -->
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
<!-- /planned-change:config-schema-strictness -->

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

```
Given the bundled read-only blueprint exists at <_project_root>/templates/config.yml
When the machine config path is resolved at process start
Then the blueprint is deep-merged underneath the machine config at <RuntimeConfig.home>/config.yml
And values already present in the machine config win over blueprint values
And blueprint keys absent from the machine config are written into it
And the machine config is rewritten only when that merge changed it
And the blueprint file itself is never written
```

#### UC-CFG-LOAD-3: Missing config.yml is a fail-fast import error

```
Given _config_path resolves to a file that does NOT exist on disk
When the machine config loads at process start
Then a FileNotFoundError is raised with the message:
  "Config file not found: <path>. Run 'telec config wizard' to create it."
And no Config object is bound (import fails for every consumer)
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

<!-- planned:config-credentials-via-config -->
#### UC-CFG-LOAD-8: Env-backed credentials remain file-declared and service-available

```gherkin
Given a human operator declares a service credential or externally supplied service identifier in machine configuration as an environment-backed placeholder
And the referenced value exists in the runtime secret environment
When the runtime loads configuration and starts the configured service
Then the typed effective configuration contains the resolved value
And the service is available using that effective configuration
And the machine configuration retains the placeholder rather than the resolved secret
And changing the process environment after configuration loading does not bypass the effective configuration
```
<!-- /planned:config-credentials-via-config -->

<!-- planned:config-tunables-via-config -->
#### UC-CFG-LOAD-9: Machine configuration governs runtime settings

```gherkin
Given a human operator has either declared an exposed runtime setting in machine configuration or left it unset
When TeleClaude starts behavior governed by that setting
Then a declared setting uses the machine-configured value
And an undeclared setting preserves the built-in runtime behavior
And ambient process environment values cannot override the selected value
```
<!-- /planned:config-tunables-via-config -->

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
<!-- planned-change:config-schema-strictness -->
- **The disallowed-runtime-keys check runs twice.** The second pass is
  redundant: `experiments.yml` merging only mutates the experiments list,
  never `computer.tmux_binary`. The duplicate is harmless — inventoried for
  cleanup, not a behavior contract.
- **No unknown-key warning at the top level.** The machine loader silently
  accepts unknown keys outside the `agents` section (unknown `agents` keys
  are rejected — see `agents-inventory-requirement.md`). A typo at e.g.
  `redis.passwrd` is silently dropped via merge.
<!-- change:config-schema-strictness -->
- **Accepted keys are parser-owned.** The machine loader rejects undeclared
  keys before default merge. Each parser declares its accepted aliases,
  dynamic named mappings, list-entry shapes, and intentionally open parameter
  bags; runtime aggregate fields, defaults, templates, and existing fleet files
  do not expand the accepted input vocabulary.
<!-- /planned-change:config-schema-strictness -->

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
