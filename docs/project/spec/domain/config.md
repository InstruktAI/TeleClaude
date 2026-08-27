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
- **Also published:** the two root resolvers — which tier governs an invocation
  (read from the file's own declaration) and where a project's shared state
  lives (read from that project root's git metadata). Both answer facts about a
  configured entity, so both are owned here; consumers call them and never walk
  the ancestor chain, read a tier declaration, or interpret git metadata
  themselves. The decomposition is
  `project/design/architecture/config-tier-resolution`.
<!-- /planned:config-kind-declaration -->

## See Also

- docs/project/spec/teleclaude-config.md
- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
