# Requirements: config-wizard-governance

## Goal

Close governance blind spots that allowed the WhatsApp adapter to ship without config wizard integration. Update four governance documents so that every future adapter or config-bearing feature is required to register its configuration surface in the wizard, env var registry, guidance registry, and config spec.

## Scope

### In scope

- Add a config-surface gate to Definition of Done.
- Strengthen DOR Gate 6 to require explicit config key and env var enumeration.
- Expand the add-adapter procedure with env var, guidance, config spec, and wizard registration steps.
- Add a maintenance note to the teleclaude-config spec requiring updates when env vars change.
- Run `telec sync` to rebuild doc indexes after edits.

### Out of scope

- Actually wiring WhatsApp into the config wizard (separate todo: `config-wizard-whatsapp-wiring`).
- Config wizard UI redesign (separate todo: `config-wizard-redesign`).
- Any code changes — this is a docs-only governance update.

## Success Criteria

- [ ] **SC-1**: DoD section 6 (Documentation) includes a checklist item: "If this work introduces new configuration surface (config keys, env vars, YAML sections), the config wizard exposes it and `config.sample.yml` includes it."
- [ ] **SC-2**: DOR Gate 6 (Dependencies & preconditions) includes: "If the work introduces new configuration, list the config keys and env vars explicitly. Confirm they will be exposed in the config wizard."
- [ ] **SC-3**: Add-adapter procedure is expanded from 5 steps to cover: env var registration in `_ADAPTER_ENV_VARS`, guidance registration in `GuidanceRegistry`, `config.sample.yml` update verification, teleclaude-config spec update.
- [ ] **SC-4**: Teleclaude-config spec includes a maintenance note: "This spec must be updated whenever config keys or env vars are added, renamed, or removed."
- [ ] **SC-5**: `telec sync` passes after all doc edits.
- [ ] **SC-6**: All four doc snippets remain valid per their frontmatter schema (id, type, scope, description fields intact).

## Constraints

- Edits must be additive — do not restructure existing gates, only extend them.
- Wording must be generic (not WhatsApp-specific) so it applies to any future adapter or config-bearing feature.
- Preserve existing snippet frontmatter and section structure.

## Risks

- Low risk: docs-only change, no runtime behavior affected.
- Only risk is wording ambiguity that fails to catch the gap in future work. Mitigated by concrete checklist items rather than vague guidance.
