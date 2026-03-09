# Requirements: Config Separation (multi-user-config)

## Goal

Split TeleClaude's monolithic config file into three layers -- system config, secrets, and per-user preferences -- with proper isolation, merge semantics, and backward compatibility for single-user mode.

## Problem Statement

Today, all configuration lives in a single `config.yml`. In a multi-user deployment, this creates three problems: (1) secrets are accessible to anyone who can read the config, (2) users cannot personalize their experience without editing the shared config, and (3) there's no distinction between system-level settings that an admin controls and personal preferences that each user owns.

## In Scope

1. **Config file hierarchy**: System config, secrets file, per-user config with defined file locations and ownership.
2. **Layer merge logic**: Deep merge with precedence rules (system -> secrets -> per-user) and per-user override restrictions.
3. **Secrets model**: A dedicated `SecretsConfig` Pydantic model for API keys, tokens, and credentials. Separate loading path with file permission checks.
4. **Per-user config model**: A subset of existing config covering only personal preferences. Validation rejects system-level keys and secrets.
5. **Config discovery**: Detection of system-wide mode (system config exists) vs single-user mode (project-root config only). Platform-aware paths for macOS and Linux.
6. **Per-user override restrictions**: Per-user config cannot set `people`, `ops`, `projects`, `database`, `computer`, `redis`, `adapters`, or any secret. Enforced at merge time.
7. **Secrets validation in per-user files**: Reject patterns that look like API keys or tokens in per-user config (heuristic check on string values matching known key patterns).
8. **Backward compatibility**: When no system config exists, the daemon loads from project-root `config.yml` exactly as today. Zero behavioral change for single-user installs.
9. **Config split migration tool**: A script/command to split an existing `config.yml` + `.env` into system/secrets/per-user files.
10. **Environment variable precedence**: Existing env vars (e.g., `ANTHROPIC_API_KEY`) continue to override both secrets file and config values.

## Out of Scope

- Service user creation and system directory setup (that's `multi-user-service`).
- Database backend changes (that's `multi-user-db-abstraction`).
- OS user identity resolution (that's `multi-user-identity`).
- Config file encryption or vault integration.
- Web-based config editor.

## Success Criteria

- [ ] Daemon loads merged config from system + secrets + per-user layers when system config exists.
- [ ] Daemon loads from single `config.yml` when no system config exists (backward compatibility).
- [ ] Secrets file (`secrets.yml`) is loaded with a file permission check: warn if readable by group/others on Unix.
- [ ] Per-user config is restricted to preference keys only. Attempts to set `people`, `database`, `computer`, `redis`, or adapter tokens raise a validation error.
- [ ] API key patterns in per-user config are rejected with a clear error message.
- [ ] Config split tool produces valid system/secrets/per-user files from an existing single config + `.env`.
- [ ] All existing tests pass without modification (backward compatibility).
- [ ] New tests cover: layer merging, override restrictions, secrets isolation, permission checks, split tool.
- [ ] Environment variables continue to take precedence over all config layers.

## Constraints

- Must use existing Pydantic model infrastructure (`teleclaude/config/schema.py`).
- Must not break the `Config` dataclass in `teleclaude/config/__init__.py` -- the final merged result is the same typed object.
- Platform-aware paths: macOS uses `/usr/local/etc/teleclaude/`, Linux uses `/etc/teleclaude/`.
- File permission check is advisory (warning), not enforced (don't refuse to start if permissions are loose -- the admin may have reasons).
- The `TELECLAUDE_CONFIG_PATH` env var continues to work as an override for the system config location.

## Risks

- **Merge complexity**: Deep merging three YAML layers with restriction enforcement adds complexity to the config loading path. Mitigation: the existing `_deep_merge` function is a solid foundation; restriction enforcement is a separate step applied after merge.
- **Key classification ambiguity**: Some keys might be debatable (is `telegram.trusted_bots` a system setting or a preference?). Mitigation: define an explicit allow-list for per-user keys; everything else is system-only.
- **Secret detection false positives**: Heuristic API key detection may flag legitimate user preferences. Mitigation: check against known key name patterns (e.g., fields ending in `_key`, `_token`, `_secret`, `_password`), not arbitrary string values.
- **Platform path detection**: macOS vs Linux path detection must be reliable. Mitigation: use `sys.platform` which is well-documented and stable.

## Design Decisions

1. **YAML for secrets, not just `.env`**: Keeps the same tooling. `.env` continues as override layer for env-var-based deployments (Docker, CI).
2. **Allow-list for per-user keys**: Rather than denying specific system keys, define what per-user CAN set. This is safer against new keys being added to the system config.
3. **Advisory permission checks**: Warn but don't block. The daemon should start even with misconfigured permissions -- the admin gets a log warning.
4. **Detection-based mode switching**: Presence of system config file triggers multi-layer loading. No explicit mode flag in any config.

## Dependencies

- `multi-user-identity` (Phase 1): In system-wide mode, the daemon must know which OS user is connecting to load the right per-user config. In single-user mode, per-user config is always `~/.teleclaude/config.yml` for the running user.
- Existing `teleclaude/config/schema.py` Pydantic models.
- Existing `teleclaude/config/__init__.py` loading infrastructure.
- Existing `teleclaude/config/loader.py` YAML loading utilities.
