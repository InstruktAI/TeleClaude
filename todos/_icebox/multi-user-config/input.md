# Multi-User Config Separation

## Origin

Extracted from `multi-user-system-install` Phase 4. The parent project transforms TeleClaude from single-user to multi-user. This phase handles config file architecture -- splitting the monolithic `config.yml` into three layers with proper isolation and merge semantics.

## Current State

Today, all configuration lives in a single `config.yml` at the project root:

- People definitions, roles, project config, adapter settings -- all in one file
- API keys and tokens are environment variables in `.env`, but there's nothing preventing them from appearing in YAML
- Per-user preferences don't exist as a concept -- there's one config for the whole system
- The config loading path (`teleclaude/config/__init__.py`) reads a single YAML file, deep-merges with defaults, and builds a typed `Config` dataclass
- The Pydantic-based loader (`teleclaude/config/loader.py`) handles `GlobalConfig`, `ProjectConfig`, and `PersonConfig` -- but these are all loaded from single files, not merged layers
- `GlobalConfig(ProjectConfig)` already has `people`, `ops`, `subscriptions` -- these are system-level concerns
- `PersonConfig` already exists with `creds`, `notifications`, `subscriptions`, `interests` -- this is the per-user model
- Validation already rejects certain keys at wrong levels (e.g., `people` at project level, `creds` at global level)

## What Needs to Change

### Three Config Layers

**System config** (`/etc/teleclaude/config.yml` or `/usr/local/etc/teleclaude/config.yml`):

- People definitions (name, identity keys, role, os_username)
- Project definitions
- Adapter settings (which adapters are enabled)
- Database connection settings
- Computer/machine identity
- Redis configuration
- Readable by all users

**Secrets** (`/etc/teleclaude/secrets.yml`):

- API keys (Anthropic, OpenAI, Google)
- Adapter tokens (Telegram bot token, Discord bot token)
- Database credentials (if PostgreSQL)
- Redis password
- SMTP credentials
- Owned by root/teleclaude service user, mode 600
- NOT readable by regular users

**Per-user config** (`~/.teleclaude/config.yml`):

- Personal preferences: thinking mode, default model, TUI settings
- Notification preferences
- Personal subscriptions and interests
- Cannot contain secrets
- Cannot override system-level settings (people, roles, projects, database, adapters)

### Merge Order

System config is the base. Secrets overlay onto it (filling in credential fields). Per-user overlays last (only for preference fields). The merge must be key-aware: per-user cannot inject keys that belong to the system layer.

### Backward Compatibility

Single-user mode (no system config exists, just `config.yml` at project root) must continue to work exactly as today. The layer system activates only when the system config path exists.

### Config Split Migration

A tool to take an existing single `config.yml` + `.env` and produce the three-layer files. This is a one-time migration aid.

## Key Design Decisions

1. **Secrets in YAML, not just `.env`**: The secrets file is YAML to keep the same config tooling. Environment variables continue to work as overrides. The `.env` file becomes optional once secrets are in the dedicated file.
2. **Per-user override restriction**: The per-user layer can only set keys in an allow-list (preferences, UI, notifications). This is enforced at merge time, not just validation time.
3. **Detection-based mode**: If `/etc/teleclaude/config.yml` exists, we're in system-wide mode. Otherwise, fall back to single-file mode. No explicit mode flag needed.

## Open Questions

1. macOS uses `/usr/local/etc/` (Homebrew convention) vs Linux `/etc/`. Do we detect platform or use a single path?
2. Should the per-user config also support per-project overrides (e.g., different thinking mode per project)?
3. How does the secrets file interact with the existing `.env` loading? Precedence order?

## Dependencies

- Phase 1 (`multi-user-identity`): Identity resolution informs which per-user config to load (we need to know the OS username to find `~username/.teleclaude/config.yml`)
- Existing Pydantic schema and validation infrastructure
