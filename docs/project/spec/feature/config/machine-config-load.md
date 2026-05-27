---
id: 'project/spec/feature/config/machine-config-load'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'v1 daemon machine config load — reads config.yml (with env-var expansion and optional experiments.yml side-file), deep-merges over DEFAULT_CONFIG, and builds the typed Config dataclass tree at module import time.'
---

# Machine Config Load — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The legacy runtime configuration surface (`config.yml`) is the single per-machine
file that tells the daemon and CLI who the computer is, which agents are
installed, where Redis is, which Discord/Telegram credentials apply, and which
remote computers are reachable. v1 loads this file once at module import time
from `teleclaude.config`, deep-merges the user's YAML over a built-in
`DEFAULT_CONFIG` mapping, expands `${ENV_VAR}` references using the
shell environment (after `.env` is sourced), optionally merges a sibling
`experiments.yml` for feature-flag entries, and produces a typed `Config`
dataclass tree (`Config`, `ComputerConfig`, `RedisConfig`, `DiscordConfig`,
`AgentConfig`, …) bound to the module-level `config` global. This is the
machine-level inventory layer; it is distinct from the `teleclaude.yml`
layered-overlay system that resolves per-workspace global/project/person
settings.

## Canonical fields

### Use cases

#### UC-CFG-LOAD-1: Default config.yml path is project root

```
Given the env var TELECLAUDE_CONFIG_PATH is NOT set
And a config.yml file exists at the repository root (<_project_root>/config.yml)
When the teleclaude.config module is imported
Then _config_path resolves to <_project_root>/config.yml
And the file is opened and yaml.safe_load reads its contents
And the resulting Config object is bound to the module-level `config` global
And the module-level `config_path` global is set to the absolute path
```

#### UC-CFG-LOAD-2: TELECLAUDE_CONFIG_PATH overrides the default

```
Given the env var TELECLAUDE_CONFIG_PATH is set to "tests/integration/config.yml"
When the teleclaude.config module is imported
Then _config_path is built from the env-var value, expanded for `~`
And if the path is relative it is resolved against _project_root
And the file at the resolved path is loaded as the machine config
```

#### UC-CFG-LOAD-3: Missing config.yml is a fail-fast import error

```
Given _config_path resolves to a file that does NOT exist on disk
When the teleclaude.config module is imported
Then a FileNotFoundError is raised with the message:
  "Config file not found: <path>. Set TELECLAUDE_CONFIG_PATH to a valid config (e.g., tests/integration/config.yml) or run 'telec config wizard' to create it."
And no Config object is bound (import fails for every consumer)
```

#### UC-CFG-LOAD-4: Environment variables in YAML values are expanded

```
Given config.yml contains a value like "${DISCORD_TOKEN}" or "${REDIS_URL:-redis://localhost:6379}"
And .env at <_project_root>/.env (or TELECLAUDE_ENV_PATH when set) has been sourced via load_dotenv
When teleclaude.config imports
Then expand_env_vars walks the parsed YAML dict and substitutes each ${VAR} reference
And substituted values flow into the merged config used by _build_config
```

#### UC-CFG-LOAD-5: DEFAULT_CONFIG values fill any gaps in user YAML

```
Given a user config.yml that omits keys such as redis.password, terminal.strip_ansi, or event_reliability.max_attempts
When _deep_merge(DEFAULT_CONFIG, _user_config) runs
Then keys absent in the user file inherit the DEFAULT_CONFIG value at every nesting level
And keys present in the user file override the default scalar
And mappings recurse: nested dicts are merged key-by-key, not replaced wholesale
And the merged dict is passed to _build_config to construct the typed Config tree
```

#### UC-CFG-LOAD-6: experiments.yml side-file appends to experiments list

```
Given config.yml is at <dir>/config.yml
And <dir>/experiments.yml exists and parses to a dict with an "experiments" key holding a list
When teleclaude.config imports after the primary config has been loaded
Then expand_env_vars runs against the experiments file too
And the parsed experiments list is appended to _user_config["experiments"]
And the combined list flows through _deep_merge into Config.experiments
```

#### UC-CFG-LOAD-7: Empty or non-dict YAML degrades into empty user config

```
Given config.yml exists but yaml.safe_load returns None or a non-dict value
When teleclaude.config imports
Then _user_config is coerced to {} (an empty dict)
And _deep_merge with DEFAULT_CONFIG produces only default values
And _build_config raises ValueError downstream because the required `agents` section is missing
```

### Implementation pointers (v1)

- `teleclaude/config/__init__.py:36-43` — `.env` resolution (`TELECLAUDE_ENV_PATH` override) and `load_dotenv` invocation; sets `WORKING_DIR` env var.
- `teleclaude/config/__init__.py:382-470` — `DEFAULT_CONFIG` mapping (single source of truth for user-configurable keys and their defaults).
- `teleclaude/config/__init__.py:473-492` — `_deep_merge(base, override)` recursive merge.
- `teleclaude/config/__init__.py:495-509` — `_validate_disallowed_runtime_keys` (rejects `computer.tmux_binary`).
- `teleclaude/config/__init__.py:706-945` — `_build_config(raw)` typed assembly (ComputerConfig, RedisConfig, EventReliabilityConfig, TelegramConfig, DiscordConfig, WhatsAppConfig, CredsConfig, AgentConfig registry, TTS/STT/Chiptunes, ExperimentConfig list, remote_computers).
- `teleclaude/config/__init__.py:948-959` — `TELECLAUDE_CONFIG_PATH` resolution and fail-fast `FileNotFoundError`.
- `teleclaude/config/__init__.py:961-967` — primary YAML read, `expand_env_vars` pass, first `_validate_disallowed_runtime_keys` call.
- `teleclaude/config/__init__.py:969-989` — optional `experiments.yml` side-file read, env expansion, append into `_user_config["experiments"]`.
- `teleclaude/config/__init__.py:991-995` — final `_deep_merge` + `_build_config` and binding of module-level `config` and `config_path` globals.

### Cross-context references

- v1 does NOT emit the `config.effective.updated` event described in
  `docs/project/spec/domain/config.md`. The initial machine config is read once
  at import time. While the daemon runs, an in-process `ConfigWatcher` re-reads on
  file change and hot-reloads the live `config` singleton in place (or self-restarts
  for connection-bound sections) — see the "Known caveats" hot-reload note — but no
  event is emitted; consumers observe the mutated singleton, not a signal.
- Consumed transitively by every module that imports `teleclaude.config` —
  daemon (`teleclaude/daemon.py`), CLI (`teleclaude/cli/`), transport
  adapters (Telegram, Discord, WhatsApp), `agent_runtime`, `output_poller`,
  `identity` (for `creds`), `remote_computers` execution paths.
- The optional `experiments.yml` side-file feeds `Config.experiments`, which
  is consumed by the daemon at startup (see
  `teleclaude/daemon.py:259-261`) and by `Config.is_experiment_enabled` —
  see the `experiment-matching` feature spec for resolution rules.
- v2 will own this as a proper bounded context with overlay computation and
  cache-invalidation events. Until cutover, `config.yml` and the
  `teleclaude.yml` overlays (see `layered-overlay-resolution` feature spec)
  coexist as two unrelated configuration mechanisms.

## Known caveats

- **Module-import side effects.** The load runs at `import teleclaude.config`
  with no opt-out. Importing the module reads files from disk, can raise
  `FileNotFoundError` or `ValueError`, and binds globals. Tests must point
  `TELECLAUDE_CONFIG_PATH` at a fixture before any code imports the module.
- **Hot reload via the daemon ConfigWatcher.** The import-time load is still
  one-shot, but the running daemon owns an in-process `ConfigWatcher`
  (`teleclaude/core/config_watcher.py`) that watches `config.yml`,
  `experiments.yml`, and `.env` (debounced async mtime poll). On a change it
  calls `reload_config()`, which re-reads from disk and mutates the live `config`
  singleton in place (identity preserved). Changed sections in
  `HOT_RELOADABLE_SECTIONS` (`summarizer`, `stt`, `tts`) take effect immediately
  — `tts` additionally via `TTSManager.reload()`. Any other changed section
  (`restart_required_sections`, the safe default) triggers a graceful
  `request_shutdown()`; launchd `KeepAlive` relaunches the daemon, which reads
  the fresh config at startup. There is no longer a launchd `WatchPaths` entry;
  the in-process watcher owns the decision.
- **`_validate_disallowed_runtime_keys` is called twice** (lines 967 and 989).
  The second call is redundant: `experiments.yml` merging only mutates the
  `experiments` list, never `computer.tmux_binary`. The duplicate is harmless
  but inventory-only — flagged for future cleanup, not a behavior contract.
- **No unknown-key warning at the top level.** v1 silently accepts unknown
  keys outside the `agents` section (unknown `agents` keys are rejected — see
  `agents-inventory-requirement` feature spec). A typo at e.g.
  `redis.passwrd` is silently dropped via merge.
- **`experiments.yml` is positional, not declared.** The side-file is read
  from the same directory as the resolved `config.yml`. There is no env-var
  override; if `TELECLAUDE_CONFIG_PATH` points elsewhere, the experiments
  side-file moves with it.
- **`_user_config` falls back to `{}` for non-dict YAML.** A `config.yml`
  whose top level is a list or scalar is silently coerced to an empty dict.
  The downstream `agents` requirement then raises, but the failure surfaces
  later than the actual cause.
- **`load_dotenv` is unconditional.** `.env` is loaded even when the file does
  not exist (no-op in that case). `TELECLAUDE_ENV_PATH` is honored, but there
  is no signal that the file was missing.
