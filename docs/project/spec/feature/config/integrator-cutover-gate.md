---
id: 'project/spec/feature/config/integrator-cutover-gate'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Integrator cutover flag requires explicit parity-evidence acceptance before it can be enabled; rollback is the default safety posture.'
---

# Integrator Cutover Gate — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

The `integrator.cutover` block on a project config controls whether the
integrator routes work through the v2 cutover path. v1 enforces a single hard
rule on this block: `enabled: true` is rejected unless
`parity_evidence_accepted: true` is also set. The rule turns "turning on
cutover" into a deliberate, human-attested act rather than a flag that can be
flipped by a config touch. The companion field
`rollback_on_incomplete_parity` defaults to `true`, encoding rollback as the
safe-by-default posture: even when cutover is enabled, the integrator falls
back to the legacy path on any signal of incomplete parity, unless the
operator explicitly opts out by setting the field to `false`. Validation runs
at YAML load time; a project that violates the gate fails to load at all,
preventing partial activation.

## Canonical fields

### Use cases

#### UC-CFG-CUT-1: Cutover disabled accepts any parity_evidence_accepted value

```
Given a project config under load with integrator.cutover.enabled = false
And integrator.cutover.parity_evidence_accepted = false (default)
When IntegratorCutoverConfig.validate_cutover_enablement runs
Then self.enabled is False
And the validator returns the IntegratorCutoverConfig unchanged
And the project is accepted with cutover disabled
```

#### UC-CFG-CUT-2: Cutover enabled without parity evidence rejected

```
Given a project config under load with integrator.cutover.enabled = true
And integrator.cutover.parity_evidence_accepted = false
When IntegratorCutoverConfig.validate_cutover_enablement runs
Then self.enabled is True AND self.parity_evidence_accepted is False
And a ValueError is raised with the message:
  "integrator.cutover.enabled requires parity_evidence_accepted=true; disable cutover to rollback until parity is accepted"
And load_project_config raises before the project is registered
```

#### UC-CFG-CUT-3: Cutover enabled with parity evidence accepted

```
Given a project config under load with integrator.cutover.enabled = true
And integrator.cutover.parity_evidence_accepted = true
When IntegratorCutoverConfig.validate_cutover_enablement runs
Then both conditions are True
And the validator returns the IntegratorCutoverConfig unchanged
And the project is accepted with cutover enabled
```

#### UC-CFG-CUT-4: Rollback-on-incomplete-parity defaults to true

```
Given a project config under load with integrator.cutover omitted
When IntegratorConfig() is constructed via default-factory
Then integrator.cutover is constructed via IntegratorCutoverConfig() default-factory
And integrator.cutover.enabled defaults to False
And integrator.cutover.parity_evidence_accepted defaults to False
And integrator.cutover.rollback_on_incomplete_parity defaults to True
And the project loads with the safe default posture
```

#### UC-CFG-CUT-5: Rollback flag can be explicitly disabled by operator

```
Given a project config under load with integrator.cutover.enabled = true
And integrator.cutover.parity_evidence_accepted = true
And integrator.cutover.rollback_on_incomplete_parity = false
When IntegratorCutoverConfig.validate_cutover_enablement runs
Then the gate passes (enabled requires parity_evidence_accepted, satisfied)
And rollback_on_incomplete_parity is honored as False
And the project loads with rollback opt-out applied
```

#### UC-CFG-CUT-6: IntegratorConfig sits on ProjectConfig

```
Given a project config under load
When ProjectConfig validation runs
Then integrator is constructed via IntegratorConfig() default-factory
And integrator.cutover is the IntegratorCutoverConfig instance under that aggregate
And the gate fires through the cutover model validator during nested validation
```

### Implementation pointers (v1)

- `teleclaude/config/schema.py:118-134` — `IntegratorCutoverConfig` with the `validate_cutover_enablement` model validator.
- `teleclaude/config/schema.py:137-141` — `IntegratorConfig` wrapper exposing `cutover: IntegratorCutoverConfig`.
- `teleclaude/config/schema.py:322` — `ProjectConfig.integrator: IntegratorConfig = IntegratorConfig()` (default-factory field that mounts the cutover block at the project level).

### Cross-context references

- Consumed by the integrator service (the worker that merges candidates to
  main) when it inspects per-project routing. The integrator reads
  `integrator.cutover.enabled` to choose between the legacy and v2 cutover
  paths; it reads `rollback_on_incomplete_parity` to decide whether to abort on
  parity-evidence gaps.
- The v2 `config` bounded context (see `docs/project/spec/domain/config.md`)
  preserves the per-project cutover gate as part of the surface that survives
  migration; the validator's semantics are part of the v2 contract.

## Allowed values

- `enabled` — `bool`. Default: `false`.
- `parity_evidence_accepted` — `bool`. Default: `false`. Must be `true` whenever `enabled` is `true`.
- `rollback_on_incomplete_parity` — `bool`. Default: `true`.

## Known caveats

- **`parity_evidence_accepted` is a flag, not a record.** The schema captures only that the operator accepted parity evidence; it does not record what evidence was accepted, who accepted it, or when. Provenance for the acceptance lives outside the config layer (commit history, operator notes).
- **Toggling cutover off does not require parity evidence.** Setting `enabled: false` is always accepted regardless of `parity_evidence_accepted`. The gate is one-way: it guards turning the flag ON, not off.
- **Default rollback posture protects the unattended case.** A project that omits the entire `integrator` block gets safe defaults (cutover off, rollback on); the gate never fires because `enabled` stays false.
- **Validation runs on every load.** A previously valid project edited out-of-band to enable cutover without flipping `parity_evidence_accepted` will fail every subsequent `load_project_config` call until the gate is satisfied or cutover is disabled.
- **`extra="allow"` admits unknown keys.** Both `IntegratorConfig` and `IntegratorCutoverConfig` accept additional YAML keys without warning; typos in field names land silently in the model.
