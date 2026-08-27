---
visibility: internal
description: Frozen v1 ownership anchor for file-backed configuration loading, validation, and operator editing.
---

# Config Domain Spec — Spec

## What it is

The v1 config area owns loading, validation, normalization, and operator editing
for the appliance's file-backed configuration. These files remain authoritative
for v1 runtime behavior while all new configuration architecture lives in
TeleClaudeNext.

## Canonical fields

- **Schema authority:** `teleclaude/config/` and the published configuration
  schema.
- **Operator surfaces:** `telec config` commands and the TUI configuration view.
<!-- planned-change:config-credentials-via-config -->
- **Runtime authority:** configuration is loaded through
  `teleclaude/runtime/config.py`; consumers do not invent fallback values.
<!-- change:config-credentials-via-config -->
- **Runtime authority:** configuration is loaded through
  `teleclaude/runtime/config.py`; externally supplied configuration values enter
  through YAML placeholder expansion at the load boundary, and consumers read
  the resolved values only from the typed configuration aggregate. Consumers
  neither consult the process environment nor invent fallback values.
<!-- /planned-change:config-credentials-via-config -->
- **Maintenance stance:** see `project/spec/domain/glossary`. File-backed configuration is not
  extended for vNext needs.

### Ownership boundary

- **Owns:** configuration schema, loading, validation, normalization, and
  operator mutation of declared settings.
- **Does not own:** business defaults invented by consumers or lifecycle policy
  for systems configured by those settings.
- **Published contracts:** validated configuration models and `telec config`
  commands; consumers never reinterpret missing or invalid values.
<!-- planned:config-kind-declaration -->
- **Also published:** the context-root resolver — which tier governs an
  invocation, read from the nearest ancestor configuration file's own
  declaration. Consumers call it and never walk the ancestor chain or read a
  tier declaration themselves.
- **Also does not own:** where a project's shared state lives. That rule reads
  the checkout-and-worktree relation rather than any configuration, and belongs
  to the context that creates linked worktrees and defines what they share.
  Carrying a configuration file is not an ownership basis. The decomposition is
  `project/design/architecture/config-tier-resolution`.
<!-- /planned:config-kind-declaration -->

## See Also

- docs/project/spec/teleclaude-config.md
- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
