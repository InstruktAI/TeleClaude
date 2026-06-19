---
description: 'Config editability is code-led and opt-in: a per-field tier declares what reaches humans; default internal.'
visibility: 'internal'
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

- The prior signal was an opt-out (`exclude_from_tui`) with default-visible
  polarity: every new field was implicitly human-editable until someone hid it,
  so agents read the whole config as editable contract. Default-internal inverts
  the polarity — a field is invisible until declared.
- One authority (the field tier) replaces three unsynced sources: the defaults
  blob, the hand-maintained sample, and the hand-curated TUI roster.

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
