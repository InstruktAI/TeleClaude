---
id: 'project/spec/feature/config/schema-driven-config-tui'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Schema-driven TUI config surface for every typed TeleClaude config layer, replacing hand-patched form models and field maps.'
---

# Schema Driven Config TUI — Spec

## Required reads

- @docs/project/spec/domain/config.md
- @docs/project/spec/teleclaude-config.md
- @docs/project/spec/feature/config/setup-wizard.md

## What it is

The config wizard's TUI renders TeleClaude configuration from the canonical
configuration schemas and their persistence surfaces, not from TUI-local shadow
models or hand-maintained field maps.

Every typed configuration layer that the wizard owns is represented as a
schema-backed editable tree:

- machine runtime `config.yml`;
- global `~/.teleclaude/teleclaude.yml`;
- project `<project>/teleclaude.yml`;
- per-person `~/.teleclaude/people/<name>/teleclaude.yml`;
- company `~/.teleclaude/companies/<slug>/teleclaude.yml` (`CompanyConfig`);
- env-backed fields declared by the env-var registry.

The TUI may still organize fields into operator-friendly tabs and sections, but
section placement is view metadata layered over the schema. It must not require
duplicating canonical config fields into TUI-only Pydantic models, duplicating
nested config paths into save maps, or excluding a valid field because nobody
hand-added it to the form.

The first visible gap this fixes is the People view: `PersonConfig.settings` and
`PersonConfig.creds` validate and drive runtime behavior, but the People TUI
only renders global `PersonEntry` fields. The broader contract is larger:
adapters, providers, summarizer, TTS/STT, infra, global/project overlays, and
per-person overlays should all use one schema-driven renderer and one
source-aware persistence path.

## Canonical fields

### Use cases

#### UC-CFG-TUI-SCHEMA-1: Config TUI renders from canonical schemas

```
Given a configuration field is declared on a canonical config model owned by the wizard
When the human opens `telec config wizard`
Then the field is reachable through the config TUI unless explicitly excluded by documented view metadata
And the renderer derives type, choices, default value, and description from the schema
And no TUI-only shadow model is required for that field to appear
```

#### UC-CFG-TUI-SCHEMA-COMPANIES: Companies tab and People company multi-reference

```
Given the company config layer (CompanyConfig) and the People identity layer
When the human opens `telec config wizard`
Then a Companies tab appears as the second tab, after Infra, rendering CompanyConfig schema-driven (honoring exclude_from_tui)
And the People tab exposes a company multi-reference field — a person may belong to multiple companies — edited as a set of company slugs
And both are schema-driven, requiring no TUI-only shadow model
```

#### UC-CFG-TUI-SCHEMA-2: View sections are metadata, not alternate models

```
Given the wizard groups config into operator-friendly sections such as Infra, Adapters, Providers, People, TTS/STT, and Env
When a section renders
Then the section uses schema-backed field descriptors from the owning config source
And section placement does not duplicate the field's canonical type or persistence path
And moving a field between sections does not change which file owns the value
```

#### UC-CFG-TUI-SCHEMA-3: People detail shows global identity and per-person overlay

```
Given the global config contains a person named "Maurice"
And ~/.teleclaude/people/Maurice Faber/teleclaude.yml exists
When the human opens `telec config wizard`
And expands Maurice in the People view
Then the detail view separates the global identity fields from the per-person overlay fields
And the global identity section is backed by PersonEntry
And the per-person overlay section is backed by PersonConfig
And both sections render from their schema fields rather than from a fixed People-field allowlist
```

#### UC-CFG-TUI-SCHEMA-4: Output visibility is editable without YAML hand edits

```
Given a person has no explicit output visibility overrides
When the human expands that person in the People view
<!-- planned-change:consolidate-injected-text-pipeline -->
Then settings.output_visibility.notifications is shown
<!-- change:consolidate-injected-text-pipeline -->
<!-- /planned-change:consolidate-injected-text-pipeline -->
Then settings.output_visibility.system_messages is shown
And settings.output_visibility.tool_calls is shown
And each value can be cycled among null, off, mobile, web, and both
When the human sets settings.output_visibility.tool_calls = off
Then the per-person overlay YAML is written with that override
And a subsequent config validation accepts the file
And projected output for that person hides tool calls on every projected surface
```

#### UC-CFG-TUI-SCHEMA-5: Credentials are first-class editable fields

```
Given a config field belongs under a credentials section owned by a typed config surface
When the human opens the config TUI section that owns that surface
Then the field is reachable through the same schema-driven renderer as non-credential fields
And the TUI does not suppress the field solely because the path contains "creds", "token", "secret", or "key"
And any masking or reveal-on-edit behavior is a rendering rule layered on top of the same editable field
```

#### UC-CFG-TUI-SCHEMA-6: Edits persist to the owning config file

```
Given the human edits a schema-rendered field
When the edit is saved
Then the write target is derived from the field's owning config source
And machine config edits write config.yml
And global overlay edits write ~/.teleclaude/teleclaude.yml
And project overlay edits write <project>/teleclaude.yml
And per-person overlay edits write that person's teleclaude.yml
And env-backed fields write through the env-var writer
And unrelated config files are not modified
```

#### UC-CFG-TUI-SCHEMA-7: Missing person overlay can be created from the TUI

```
Given a global PersonEntry exists for a person
And no matching per-person overlay file exists
When the human expands that person in the People view
Then the per-person overlay section renders the PersonConfig defaults
And saving any overlay field creates ~/.teleclaude/people/<name>/teleclaude.yml
And the written file validates as PersonConfig
```

#### UC-CFG-TUI-SCHEMA-8: Existing config flows do not regress

```
Given the current config TUI supports guided setup, env editing, adapter/provider editing, People editing, validation, and refresh
When the schema-driven config TUI is delivered
Then those existing flows continue to work
And previously supported enum cycling, boolean toggling, list editing/reordering, and text editing remain available
And existing validation checks still run from the TUI
And writes continue to use the existing atomic writer contracts for their target surfaces
```

#### UC-CFG-TUI-SCHEMA-9: Internal fields are excluded by schema-declared view metadata

```
Given a configuration field is runtime-derived, system-resolved, or otherwise not operator-editable
And that field is marked excluded in the schema's view metadata
When the human opens `telec config wizard`
Then the field does not render in the config TUI
And the exclusion decision is read from the schema's view metadata, not from a TUI-local field name list
And the retired TUI-local name blacklist is no longer the authority for exclusion
And the operator can still edit the field by hand in its underlying YAML or config.yml file
Given a field is operator-editable infrastructure such as a Redis connection tuning field
Then it renders in the same Infra section that already exposes the Redis URL and password
And no separate advanced section is introduced to hold it
```

#### UC-CFG-TUI-SCHEMA-10: Nested structures render recursively to their leaves

```
Given a configuration field holds a nested structure — a nested model, a dataclass, or a dict whose values are models or dataclasses
When the config TUI renders the owning section
Then each leaf of the nested structure renders as its own editable field keyed by its full dotted path
And no nested structure renders as a serialized dict or JSON blob
And an unset optional nested structure still renders its leaf fields, derived from the declared type
And editing a nested leaf persists to that leaf's dotted path in the owning config file
```

#### UC-CFG-TUI-SCHEMA-11: Env-sourced values are masked unless the field is being edited

```
Given a rendered field whose value is sourced from an environment variable
When the field is displayed and is not being edited
Then its value is shown masked
When the human edits the field
Then the actual value is revealed in the edit buffer
And masking is a rendering rule only, leaving the persistence target and editability unchanged
```

#### UC-CFG-TUI-SCHEMA-12: Nested structures render as an indented tree

```
Given reflected fields whose dotted keys describe a nested structure
When the config TUI renders the owning subtab or person overlay
Then each level renders indented beneath its parent as a labelled branch header
And leaves render beneath their branch at a depth matching their key
And two leaves that share a name under different parents (e.g. stt.services.openai and tts.services.openai) render under their own branches without merging
```

#### UC-CFG-TUI-SCHEMA-13: Default values are shown even when the user config omits them

```
Given a configuration section whose defaults include nested entries the user config does not set
When the config TUI renders that section
Then the effective value (user value over default) is shown for every field
And default-only nested entries (e.g. TTS services present only in the defaults) are still rendered
```

#### UC-CFG-TUI-SCHEMA-14: Persistence is sparse — defaults are not stored

```
Given a machine-config field is edited through the config TUI
When the saved value equals that field's default
Then the field is removed from config.yml rather than written
And emptied parent tables are removed with it
And the field still renders via the default on the next load
When the saved value differs from the default
Then only that deviation is written to config.yml
```

#### UC-CFG-TUI-SCHEMA-15: Visibility is opt-in via a per-field tier

```
Given a machine-config field carries a `tier` declaration in code
And the tier defaults to `internal` when no declaration is present
When the human opens `telec config wizard`
Then only fields declared `tier=tui` render in the config TUI
And `internal` and `public` fields do not render
And the tier declaration is the view-metadata authority, not a TUI-local field name list
Given a new machine-config field is added without a tier declaration
Then it is `internal` and does not render in the config TUI
And it is absent from the generated config.yml public sample
```

<!-- planned:person-scoped-mcp-credentials -->

#### UC-CFG-TUI-SCHEMA-16: People exposes registry-derived personal secrets

```
Given the MCP registry contains a person-scoped server whose launch definition references `OMI_API_KEY`
And a configured person exists
When an authorized operator expands that person in the People view
Then a Secrets section shows `OMI_API_KEY` with set or unset status
And it shows which personal MCP servers require the key
And the inventory is derived from the MCP registry plus existing keys in that person's secret store
And no duplicate secret list or value is stored on PersonConfig
And the value is masked outside an active edit
When the operator keeps, replaces, or clears the secret explicitly
Then only that person's owner-only secret file is preserved or mutated atomically
And unrelated person YAML, global environment, and other person secret files remain unchanged
```

<!-- /planned:person-scoped-mcp-credentials -->

The `tui` tier is the wizard's render set: the operator-facing fields the config
wizard shows, declared per field in code. The `tier` marker is the opt-in form of
the schema view metadata named in UC-CFG-TUI-SCHEMA-9 — declaration to show,
rather than a flag to hide — so the rendered set is the inverse of the retired
exclusion list, not a reduction of it. The governing rule lives in
`project/policy/config-public-surface`.

### Current hand-patched surfaces to retire

The current TUI config surface contains dynamic reflection machinery, but the
inputs to that machinery are still hand-patched:

- TUI-local Pydantic models mirror adapter, provider, Redis, summarizer, STT,
  and TTS fields instead of reflecting the canonical config models directly.
- The active subtab builds reflected fields with bespoke code per section.
- Save routing depends on manually maintained section-prefix and flat-key maps.
- The People subtab bypasses the reflected-field renderer and hand-renders
  `PersonEntry` fields.
- The People save path always writes the global config, so per-person overlay
  fields cannot be edited there.
- Field exclusion is a flat, hand-maintained name set in the TUI reflection
  module (the `_BLACKLIST`), divorced from the schema. It holds runtime-derived
  Discord channel identifiers, system-resolved paths, and complex structures —
  the same TUI-local hand-patched authority this delivery eliminates on the show
  side, applied to the hide side.

Delivery retires these as sources of truth. View metadata may remain, but it
must point at canonical schema paths and persistence sources. Exclusion is moved
onto the schema as view metadata (UC-CFG-TUI-SCHEMA-9); the TUI-local name
blacklist is retired as the authority.

### Cross-context references

- `project/spec/domain/config` owns the typed overlay schemas and the
  `PersonConfig.settings.output_visibility` value object.
- `project/spec/teleclaude-config` names the files, keys, env vars, and
  ownership boundaries the TUI must honor.
- `project/spec/feature/config/setup-wizard` owns the broader wizard
  guarantees: single setup surface, idempotent re-runs, persisted-state resume,
  and write-then-read rendering after edits.

<!-- planned:person-scoped-mcp-credentials -->

- `project/spec/feature/agent_runtime/lazy-mcp-runtime` owns personal MCP credential requirements and owner-scoped lease behavior; the People view projects its registry requirements without becoming their source of truth.

<!-- /planned:person-scoped-mcp-credentials -->

## Allowed values

- Output visibility override values: `null`, `off`, `mobile`, `web`, `both`.
- Schema field source: canonical config models or env-var registry descriptors.
- Persistence source: machine config, global overlay, project overlay,
  per-person overlay, or env file.
- Field render disposition: `visible` (rendered through the schema-driven
  renderer) or `excluded` (marked in schema view metadata as runtime-derived,
  system-resolved, or otherwise non-operator-editable; hand-editable in its
  YAML/`config.yml` file but not shown in the TUI).

## Known caveats

- Current implementation has reflection helpers, but not a full schema-driven
  config tree. The rework should reuse the useful renderer pieces where they
  fit, while replacing TUI-local config models and path maps as authority.
- Some runtime config is still dataclass-backed rather than Pydantic-backed.
  The renderer may support both dataclasses and Pydantic models, but the source
  of truth remains the canonical runtime aggregate, not a TUI-only projection.
- `PersonConfig` and other overlay models accept unknown extra keys. The TUI
  should preserve unknown keys when writing known fields, but it does not need
  to invent editors for arbitrary unknown subtrees in this delivery.
- Masking is keyed on value provenance, not on field-name heuristics: a value
  resolved from an environment variable (`${VAR}` reference) is masked unless the
  field is being edited (UC-CFG-TUI-SCHEMA-11). Masking is a rendering rule layered
  over the same editable field and does not change the persistence contract.
- `invite_token` is relocated out of `PersonConfig` into an ephemeral
  invitations store under `~/.teleclaude/state/` by this delivery. The config
  delta is the field's removal from the `PersonConfig` overlay; the invitation
  handshake itself (binding a transport handle to a known person) is an identity
  concern, so the relocated store is identity-conceptual ephemeral state, not a
  config overlay. The token is therefore absent from the per-person overlay
  section by construction, not by an exclusion rule. The relocation keeps invite
  generation and Telegram/Discord redemption working; the TUI never renders or
  edits the invitations store.
- The hidden set delivered via schema view metadata (UC-CFG-TUI-SCHEMA-9)
  includes machine Discord runtime channel identifiers and the category map,
  system-resolved computer fields, agent-runtime internals resolved by policy,
  and adapter QoS tuning blocks. Relocating the Discord channel identifiers out
  of config entirely (the way `invite_token` is relocated) is explicitly a
  follow-up, not part of this delivery — they are only hidden here.
