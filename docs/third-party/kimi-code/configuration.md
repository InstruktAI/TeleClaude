---
description: Kimi Code 0.37.2 TOML configuration roots, local override behavior, and installed validation surface.
---

# Kimi Code Configuration

## Configuration roots

Kimi Code reads its user configuration from
`$KIMI_CODE_HOME/config.toml`, with `~/.kimi-code` as the documented default
home. The installed 0.37.2 home contains both `config.toml` and `tui.toml`;
`kimi doctor config` and `kimi doctor tui` validate those respective formats.

The vendor documents a project-local `<project-root>/.kimi-code/local.toml`.
Its `[workspace].additional_dir` records remembered extra workspace paths and
is machine-specific because those paths are absolute.

## Effective settings

The installed configuration uses model aliases, provider tables, thinking
settings, notifications, and upgrade settings. The documented top-level
controls also include `default_permission_mode`, `default_plan_mode`,
`extra_skill_dirs`, `extra_agent_dirs`, `hooks`, and `permission` rules.

For ordinary runtime settings, launch flags override the user config for that
run. The documented permission modes are `manual`, `yolo`, and `auto`.
Provider credentials belong in TOML configuration, not ordinary shell
environment variables; documented environment overrides are explicit,
field-specific exceptions.

## Gaps

- Installed configuration values and credentials were not recorded.
- The runtime precedence chain was not exercised with competing user, project,
  and environment values.

## Sources

- https://moonshotai.github.io/kimi-code/en/configuration/config-files
- https://moonshotai.github.io/kimi-code/en/configuration/overrides.html
- https://moonshotai.github.io/kimi-code/en/configuration/env-vars.html
