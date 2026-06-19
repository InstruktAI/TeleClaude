---
description: 'Config editability is code-led and opt-in: a per-field tier declares what reaches humans; default internal.'
visibility: 'internal'
delivered_by:
  - config-public-surface-contract
needs_domain_baseline: true
---

# Config Public Surface — Policy

## Rules

- Every machine-config field carries an editability **tier**, declared in code on
  the field: `internal` (the default), `public`, or `tui`.
- **`internal` is the default.** A field with no tier marker is internal —
  constants, TTLs, QoS blocks, box sizes, channel identifiers, and
  runtime-derived or system-resolved values. It is absent from the generated
  sample, absent from the config TUI, and not presented as human-editable.
- **`public`** fields are the `config.yml` surface. They appear in the generated
  `templates/config.yml`; agents patch `config.yml` directly.
- **`tui`** is the headline subset of `public`. It is the only tier the config
  wizard renders.
- A field reaches humans only by a deliberate tier declaration. A new field with
  no marker stays internal.
- The field tiers are the single authority for what is public. The
  `DEFAULT_CONFIG` defaults blob and the generated `templates/config.yml` sample
  are consequences of the markers, not independent sources of the public surface.

## Rationale

- Default-internal editability prevents accidental human exposure: a field is
  invisible until declared.
- One authority (the field tier) keeps the defaults blob, the generated sample,
  and the TUI render set aligned.

## Scope

- Applies to the machine runtime configuration (`config.yml`, the
  `TeleclaudeConfig` aggregate) and the configuration models the TUI renders.

## Enforcement

- A reviewer treats a human-facing field carrying no deliberate `public` or `tui`
  tier as a defect.
- `telec sync` generates `templates/config.yml` from the `public` and `tui`
  tiers; a hand-edited sample is overwritten on the next sync.

## Exceptions

- None.
