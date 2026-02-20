# Implementation Plan: Config Separation (multi-user-config)

## Overview

Split config loading into a three-layer system (system, secrets, per-user) while maintaining full backward compatibility with single-file mode. The approach adds layer discovery and merge logic to the existing config loading path, introduces a `SecretsConfig` Pydantic model, defines a per-user config allow-list, and provides a migration tool to split existing configs.

The existing `_deep_merge` function and Pydantic validation infrastructure provide the foundation. The main additions are: (1) multi-file discovery, (2) secrets-specific loading with permission checks, (3) per-user restriction enforcement, and (4) a config split CLI command.

## Phase 1: Config Discovery and Layer Loading

### Task 1.1: Platform-aware config path resolution

**File(s):** `teleclaude/config/paths.py` (new)

- [ ] Create a config paths module with platform-aware defaults:
  - `system_config_path()`: `/usr/local/etc/teleclaude/config.yml` on macOS, `/etc/teleclaude/config.yml` on Linux
  - `system_secrets_path()`: `/usr/local/etc/teleclaude/secrets.yml` on macOS, `/etc/teleclaude/secrets.yml` on Linux
  - `user_config_path(username=None)`: `~/.teleclaude/config.yml` (or `~username/.teleclaude/config.yml` if username provided)
  - `is_system_mode()`: returns True if system config path exists
- [ ] Support `TELECLAUDE_CONFIG_PATH` env var to override system config location
- [ ] Support `TELECLAUDE_SECRETS_PATH` env var to override secrets location
- [ ] Support `TELECLAUDE_USER_CONFIG_PATH` env var to override per-user config location

### Task 1.2: Secrets config model

**File(s):** `teleclaude/config/schema.py`

- [ ] Add `SecretsConfig` Pydantic model with fields for:
  - `anthropic_api_key: Optional[str]`
  - `openai_api_key: Optional[str]`
  - `google_api_key: Optional[str]`
  - `telegram_bot_token: Optional[str]`
  - `discord_token: Optional[str]`
  - `redis_password: Optional[str]`
  - `database_password: Optional[str]`
  - `smtp_user: Optional[str]`
  - `smtp_pass: Optional[str]`
- [ ] Add validation: all fields must be string or None (reject nested objects)
- [ ] Add model config: `extra = "allow"` for forward compatibility with new secret keys

### Task 1.3: Per-user config model

**File(s):** `teleclaude/config/schema.py`

- [ ] Add `UserPreferencesConfig` Pydantic model defining the allow-list:
  - `ui: Optional[UIPreferences]` (animations, theming, etc.)
  - `terminal: Optional[TerminalPreferences]` (strip_ansi)
  - `thinking_mode: Optional[str]` (default thinking mode preference)
  - `default_agent: Optional[str]` (preferred agent)
  - `notifications: Optional[NotificationsConfig]`
  - `interests: Optional[List[str]]`
  - `tts: Optional[TTSPreferences]` (personal TTS settings)
- [ ] Add model validator that rejects system-level keys: `people`, `ops`, `database`, `computer`, `redis`, `telegram`, `discord`, `hooks`, `jobs`, `subscriptions`, `business`, `git`, `channel_subscriptions`
- [ ] Add validator that rejects secret-like values: scan string fields for patterns matching API keys (`sk-`, `xoxb-`, etc.) and field names ending in `_key`, `_token`, `_secret`, `_password`

### Task 1.4: Multi-layer config loading

**File(s):** `teleclaude/config/__init__.py`

- [ ] Refactor the module-level config loading to support two modes:
  - **System mode** (system config exists): Load system config -> merge secrets -> merge per-user -> build `Config`
  - **Single-user mode** (no system config): Load project-root `config.yml` as today (no change)
- [ ] Extract the current loading logic into a `_load_single_user_config()` function
- [ ] Add `_load_system_config()` function that:
  1. Loads system `config.yml` via `yaml.safe_load`
  2. Loads `secrets.yml` (with permission check)
  3. Merges secrets into system config (secrets fill credential fields)
  4. Loads per-user `config.yml` (validated as `UserPreferencesConfig`)
  5. Merges per-user preferences (restricted to allow-list keys)
  6. Deep merges with `DEFAULT_CONFIG`
  7. Builds `Config` via `_build_config`
- [ ] Add `_check_file_permissions(path)` helper: warns via logger if file is group/world readable (Unix `stat` check)
- [ ] Integrate secrets into environment: set env vars from secrets file so downstream code (adapters, API clients) picks them up via existing `os.getenv()` calls
- [ ] Preserve `TELECLAUDE_CONFIG_PATH` override behavior

### Task 1.5: Secrets-to-environment bridge

**File(s):** `teleclaude/config/__init__.py`

- [ ] After loading secrets, map secret fields to environment variables:
  - `anthropic_api_key` -> `ANTHROPIC_API_KEY`
  - `openai_api_key` -> `OPENAI_API_KEY`
  - `google_api_key` -> `GOOGLE_API_KEY`
  - `telegram_bot_token` -> `TELEGRAM_BOT_TOKEN`
  - `discord_token` -> `DISCORD_TOKEN` (if applicable)
  - `redis_password` -> used directly in RedisConfig construction
  - `database_password` -> used directly in DatabaseConfig construction
  - `smtp_user` -> `SMTP_USER`, `smtp_pass` -> `SMTP_PASS`
- [ ] Only set env vars if they are not already set (env vars take precedence)
- [ ] Log at debug level which secrets were loaded from file vs environment

---

## Phase 2: Config Split Migration Tool

### Task 2.1: Config split logic

**File(s):** `teleclaude/config/split.py` (new)

- [ ] Create `split_config(config_path, env_path, output_dir)` function that:
  1. Reads existing `config.yml`
  2. Reads existing `.env` (if present)
  3. Classifies each top-level key into system/secrets/per-user
  4. Extracts API keys and tokens from `.env` into secrets dict
  5. Writes `config.yml` (system), `secrets.yml`, and `user-config.yml` to output_dir
  6. Sets file permissions on `secrets.yml` to 600
- [ ] Key classification:
  - **System**: `computer`, `database`, `redis`, `telegram`, `discord`, `polling`, `people`, `ops`, `business`, `hooks`, `jobs`, `git`, `subscriptions`, `channel_subscriptions`
  - **Secrets**: values from `.env` matching known key names, plus any `token`, `password`, `api_key` fields found in YAML
  - **Per-user**: `ui`, `terminal`, `tts`, `stt`, `experiments`, `interests`
- [ ] Validate the output: reload each file with its respective model and ensure no validation errors

### Task 2.2: CLI command for config split

**File(s):** `teleclaude/cli/commands/config_split.py` (new or integrated into existing CLI)

- [ ] Add a `telec config split` subcommand (or standalone script `bin/split-config.py`)
- [ ] Arguments: `--config PATH` (default: `./config.yml`), `--env PATH` (default: `./.env`), `--output-dir PATH` (default: `/etc/teleclaude/` or `/usr/local/etc/teleclaude/`)
- [ ] Dry-run mode: `--dry-run` prints what would be written without writing
- [ ] Confirmation prompt before overwriting existing files

---

## Phase 3: Validation and Tests

### Task 3.1: Unit tests for config layer loading

**File(s):** `tests/unit/test_config_layers.py` (new)

- [ ] Test system mode detection: returns True when system config exists, False otherwise
- [ ] Test single-user fallback: when no system config, loads exactly as before
- [ ] Test layer merge: system + secrets + per-user produces expected merged config
- [ ] Test per-user restriction: setting `people` in per-user config raises validation error
- [ ] Test per-user restriction: setting `database` in per-user config raises validation error
- [ ] Test secrets isolation: API key pattern in per-user config raises validation error
- [ ] Test permission check: warns on group-readable secrets file (mock `os.stat`)
- [ ] Test env var precedence: env var set before config load wins over secrets file value
- [ ] Test platform paths: macOS returns `/usr/local/etc/`, Linux returns `/etc/`

### Task 3.2: Unit tests for config split tool

**File(s):** `tests/unit/test_config_split.py` (new)

- [ ] Test split produces three valid files from a sample monolithic config + `.env`
- [ ] Test split correctly classifies system vs secrets vs per-user keys
- [ ] Test split extracts env vars into secrets file
- [ ] Test split round-trip: split then load from layers produces equivalent config
- [ ] Test dry-run mode produces no file writes

### Task 3.3: Quality checks

- [ ] Run `make test` -- all existing tests pass
- [ ] Run `make lint` -- no new lint violations
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)

## Risks and Mitigations

- **Risk**: Deep merge with restriction enforcement adds complexity. **Mitigation**: Restriction check is a separate pass after merge -- keeps merge logic clean.
- **Risk**: Secret pattern detection may have false positives. **Mitigation**: Check field names (not values) against a known list; values only checked against well-known prefixes (`sk-`, `xoxb-`, etc.).
- **Risk**: Breaking existing config loading. **Mitigation**: Single-user path is the existing code extracted into a function -- minimal change surface.

## Files Changed Summary

| File                                      | Change                                                         |
| ----------------------------------------- | -------------------------------------------------------------- |
| `teleclaude/config/paths.py`              | New: platform-aware config path resolution                     |
| `teleclaude/config/schema.py`             | Add: `SecretsConfig`, `UserPreferencesConfig` models           |
| `teleclaude/config/__init__.py`           | Modify: multi-layer loading, secrets bridge, permission checks |
| `teleclaude/config/split.py`              | New: config split migration logic                              |
| `teleclaude/cli/commands/config_split.py` | New: CLI command for config split                              |
| `tests/unit/test_config_layers.py`        | New: layer loading tests                                       |
| `tests/unit/test_config_split.py`         | New: split tool tests                                          |
