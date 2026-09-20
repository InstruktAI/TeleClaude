---
description: 'Config editability is code-led and opt-in: a per-field tier declares
  what reaches humans; default internal.'
visibility: internal
---

# Config Public Surface — Policy

## Rules

- Every machine-config field carries an editability **tier**, declared in code on
  the field: `internal` (the default), `public`, or `tui`.
- **`internal` is the default.** A field with no tier marker is internal —
  constants, TTLs, QoS blocks, box sizes, channel identifiers, and
  runtime-derived or system-resolved values. It is absent from a generated
  machine configuration, absent from the config TUI, and not presented as
  human-editable.
<!-- planned-change:move-discord-reflection-state-to-db -->
- **`public`** fields are the `config.yml` surface; agents patch `config.yml`
  directly.
<!-- change:move-discord-reflection-state-to-db -->
- **`public`** fields are the `config.yml` surface. Agents mutate them through
  `telec config`; runtime and UI callers submit named semantic operations to
  the config context. The backing file is not an agent or caller editing
  surface.
<!-- /planned-change:move-discord-reflection-state-to-db -->
- **`tui`** is the operator-facing render set: the only tier the config wizard
  renders.
- **A field may additionally be declared sensitive.** Sensitivity and tier are
  independent declarations: sensitivity decides how a value is carried, tier
  decides whether the field is rendered at all. A sensitive field is written into
  a generated machine configuration as its environment reference and never as its
  value. A sensitive field that is also in the TUI render set reports whether it
  is set and never its value.
- **A sensitive field's environment variable is its dotted path, upper-cased,
  with each separator replaced by a single underscore.** The mapping is defined
  from schema to name only.
- **A field inside a body declared `ungoverned_body` carries no derived
  reference.** Any reference in such a body is operator-authored.
- A field reaches humans only by a deliberate tier declaration. A new field with
  no marker stays internal.
- The field markers are the single authority for what is public and what is
  secret. The `DEFAULT_CONFIG` defaults blob and any generated machine
  configuration are consequences of the markers, never independent sources.
- **A container of structured members is never silently treated as a leaf.** Its
  members carry their own tiers, so a schema walk that steps over the container
  leaves those tiers claiming a surface nothing generates, reconciles, or
  enforces. Such a field is governed member-by-member, or it declares
  `ungoverned_body` with the reason it is not; an unmarked one raises at walk
  time rather than resolving to a leaf. The reason is a non-empty string, never a
  bare flag — a marker that any truthy value satisfies is a suppression switch
  wearing a declaration's name.
- The declaration records a fact, it does not grant an exemption, and the fact
  must be true of the code that builds the field. Membership authored in the
  config file — list entries, operator-named provider keys — has no static leaf
  for the walk to address and says exactly that. A **closed** vocabulary
  modelled as an open `dict[str, …]` does not qualify: it is a typing gap, keyed
  by the enum that already defines its membership so the walk reaches its
  members.

## Rationale

<!-- planned:move-discord-reflection-state-to-db -->
- Routing mutation through the config context preserves one transaction-wide
  lock and validation-before-replacement authority; direct backing-file edits
  would split that authority between callers.
<!-- /planned:move-discord-reflection-state-to-db -->

- Default-internal editability prevents accidental human exposure: a field is
  invisible until declared.
- One authority (the field markers) keeps the defaults blob, the TUI render set,
  and the environment surface aligned.
- No nesting separator is introduced because the mapping is never inverted: the
  schema names the variable, and nothing derives a field from a name.
- A member the schema does not enumerate cannot carry a derived reference, which
  is why an `ungoverned_body` keeps its references authored.
- A deployment command that writes a git-tracked file leaves the working tree
  dirty and makes a repository edit nobody asked for.

## Scope

- Applies to the machine runtime configuration (`config.yml`, the
  `TeleclaudeConfig` aggregate) and the configuration models the TUI renders.

## Enforcement

- A reviewer treats a human-facing field carrying no deliberate `public` or `tui`
  tier as a defect.

- No command writes a git-tracked configuration file. A machine configuration is
  produced from the markers when none exists, and is not reconciled afterwards.
- A reviewer treats a credential-bearing field carrying no sensitivity
  declaration as a defect, because its value would be written where a reference
  belongs.

## Exceptions

- None.
