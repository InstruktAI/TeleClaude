# Input: config-wizard-governance

## Problem

The WhatsApp adapter shipped without wizard integration because **nothing in our governance enforces it**. The Definition of Done, Definition of Ready, and add-adapter procedure all have blind spots around config UI integration. This means every future adapter or config-bearing feature risks the same gap.

## Evidence

### Definition of Done (`software-development/policy/definition-of-done.md`)

- 8 quality gates, none mention config wizard or `config.sample.yml`
- Documentation gate says "CLI help text updated" but not "config wizard updated"
- No gate catches missing env var registration

### Definition of Ready (`software-development/policy/definition-of-ready.md`)

- Gate 6 (Dependencies): "Required configs, access, and environments are known" — developer awareness only, no requirement to plan wizard integration
- Gate 8 (Tooling impact): covers scaffolding procedures but not config UI
- No gate asks "does this work add new configuration surface? If so, how will it be exposed?"

### Add-Adapter Procedure (`project/procedure/add-adapter`)

- Step 3: "Add configuration keys to `config.sample.yml`" — exists but wasn't followed for WhatsApp
- No step for: env var registration in `_ADAPTER_ENV_VARS`, guidance registration, wizard component wiring
- Only 5 steps total — too sparse for the actual registration surface

### Teleclaude-Config Spec (`project/spec/teleclaude-config`)

- Machine-readable surface lists env vars but has no WhatsApp entries
- No maintenance rule requiring spec update when env vars change
- Stale since WhatsApp was added

## Success Criteria

1. **DoD** has a new gate (under Documentation or as a new section) requiring: "If this work introduces new configuration surface (config keys, env vars, YAML sections), the config wizard exposes it and `config.sample.yml` includes it."
2. **DOR** Gate 6 includes: "If the work introduces new configuration, list the config keys and env vars explicitly. Confirm they will be exposed in the config wizard."
3. **Add-Adapter procedure** is expanded with steps for: env var registration in `_ADAPTER_ENV_VARS`, guidance registration in `GuidanceRegistry`, component wiring or verification, `config.sample.yml` update verification, teleclaude-config spec update
4. **Teleclaude-Config spec** has a maintenance note: "This spec must be updated whenever config keys or env vars are added, renamed, or removed."

## Key Files

- `docs/global/software-development/policy/definition-of-done.md`
- `docs/global/software-development/policy/definition-of-ready.md`
- `docs/project/procedure/add-adapter.md`
- `docs/project/spec/teleclaude-config.md`
