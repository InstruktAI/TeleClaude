---
description: 'Per-person identity schema declaring name, validated email, optional username, role enum, nested expertise map, and deprecated single-level proficiency field.'
visibility: 'public'
---

# Person Identity Schema — Spec

## Required reads

- @docs/local/spec/domain/config.md

## What it is

A `PersonEntry` declares the identity of a human principal in the platform's
global configuration. v1 keeps the schema deliberately narrow: a required
`name`, a required and stripped-non-empty `email`, an optional Telegram-style

`username`, an optional platform `role` chosen from a closed enum
(`admin | member`, absent when the person holds no platform role), and a nested

`expertise` map that captures domain proficiency at one or two levels. The
single-level `proficiency` field is preserved on the model for backward
compatibility but is deprecated in favor of `expertise`. Entries are collected
into the global overlay's people list, the only list inside the global config that names
principals; per-person `creds`, `notifications`, and `timezone` live in
separate per-person config files (see the global-level disallowed-keys rule).
Validation strips whitespace from `email` and persists the stripped value, so
downstream consumers can rely on the stored email being canonicalized.

A canonical, stable, kebab-case `slug` is the single reference key for a
person. The per-person workspace folder (`~/.teleclaude/people/<slug>/`) and
every folder-keyed lookup resolve through `slug`; `name` is display and `email`
is the contact identifier. The slug is validated at load time with the shared
slug validator — the same format the project slug enforces — so empty,
whitespace-only, or absent normalizes to `None` and any non-empty value must be
kebab-case. Once set, the slug never changes.

## Canonical fields

<!-- planned:issue-129 -->

### Person-owned GitHub declaration

The person overlay declares the human's GitHub handle separately from the
registry's Telegram-style username. The typed declaration is owned by
`teleclaude/config/github_schema.py` and participates in the person schema,
published editor metadata and kind-addressed person get/patch operations.
Replacement and explicit clearing use the existing configuration writer's
clearance, revision, candidate-validation and file-transaction boundary;
unrelated registry and overlay fields retain their stored values
(`local/projects/teleclaude/spec/feature/config/kind-addressed-configuration`).

An absent declaration is valid and establishes no GitHub/person association.
Declaring a handle is separate from validating its provider account, which is
identity-owned under
`local/projects/teleclaude/spec/feature/identity/person-context-binding`.
The declaration contains no credential and is never a platform actor or a
credential-selection fallback
(`general/policy/human-contract`, `sdlc/policy/security-awareness`).
<!-- /planned:issue-129 -->

### Use cases

#### UC-CFG-PERSON-1: An operator registers a person for identity resolution

```
Given an operator needs TeleClaude to recognize a person
When they register the person's name and contact email
Then the person is available for identity resolution by that email
```

#### UC-CFG-PERSON-2: Empty email rejected before storage

#### UC-CFG-PERSON-3: Email whitespace is stripped on persist

#### UC-CFG-PERSON-4: min_length=1 on email field rejects empty literal

#### UC-CFG-PERSON-5: An operator assigns a supported platform role

```
Given an operator needs to assign platform standing to a person
When they configure the person as an administrator or member
Then the person's platform role reflects that choice
```

#### UC-CFG-PERSON-6: Role enum rejects unknown values

#### UC-CFG-PERSON-7: An operator configures a person's expertise profile

```
Given an operator wants assistance calibrated to a person's expertise in different domains
When they configure that person's expertise profile
Then the profile preserves the declared expertise levels by domain
```

#### UC-CFG-PERSON-8: Nested expertise map accepted

#### UC-CFG-PERSON-9: Expertise with unknown proficiency level rejected

#### UC-CFG-PERSON-10: Deprecated `proficiency` field still parses

#### UC-CFG-PERSON-11: Global overlay collects people as a list

#### UC-CFG-PERSON-12: Global-level disallowed keys are rejected near people

#### UC-CFG-PERSON-13: A person's workspace remains tied to a stable identity

```
Given an operator creates a workspace for a person whose display name may change
When the person's identity is registered with its canonical slug
Then the workspace remains associated with that person after a display-name change
```

#### UC-CFG-PERSON-14: Empty or absent slug normalizes to None for legacy load

#### UC-CFG-PERSON-15: Invalid slug format rejected

#### UC-CFG-PERSON-16: Legacy person without slug is migrated on load

### Cross-context references

- Consumed by the identity bounded context — the principal resolver reads
  the global `people` list to find a principal by name, email, or
  username; the role drives capability gating in the identity context.
- Per-person `creds`, `notifications`, and `timezone` live in the
  per-person config overlay, not on the person entry itself. The entry is
  identity-only; runtime preferences live alongside the person's
  workspace.
- The `config` bounded context (`local/projects/teleclaude/spec/domain/config.md`)
  preserves the person-entry shape; the effective-configuration merge
  keeps the same identity fields exposed to downstream consumers.

## Allowed values

- `name` — non-empty string. Required.
- `email` — string, stripped, non-empty after strip. Required. `Field(min_length=1)` rejects an empty literal before the validator runs.
- `username` — optional string. Default: `None`.

- `role` — `"admin" | "member"`, or `None` when the person holds no platform role. Default: `None`.

- `expertise` — optional `dict[str, ProficiencyLevel | dict[str, ProficiencyLevel]]`. Default: `None`.
- `proficiency` — optional `ProficiencyLevel`. **Deprecated** — use `expertise` instead. Default: `None`.
- `slug` — `None`, or a non-empty kebab-case string matching the shared slug pattern `^[a-z0-9]+(?:-[a-z0-9]+)*$` after stripping. Empty, whitespace-only, or absent normalize to `None`. The canonical, stable reference key for the person; populated by `telec config person init`, and immutable thereafter.

## Known caveats

- **No format validation on `email`.** The validator only enforces non-emptiness after strip; any non-empty string passes (no `@` requirement, no domain validation). Consumers receive whatever the operator wrote, minus surrounding whitespace.
- **`slug` is the stable reference key; `name` is display only.** `slug` is the canonical, immutable key the workspace folder and every folder-keyed lookup resolve through. `name` may change freely and is unique only by convention; renaming a person updates `name` without touching `slug` or the workspace folder. Uniqueness of `slug` is enforced at creation (`ensure_unique_slug`), not by the schema — two on-disk entries with the same `slug` each load, and the collision matters only at folder resolution.
- **`proficiency` and `expertise` are not jointly validated.** A `PersonEntry` may carry both fields at once; the schema accepts the combination without warning. Consumers choosing to honor `expertise` over `proficiency` must implement that preference themselves.
- **Expertise nesting depth is fixed at two.** The type `dict[str, ProficiencyLevel | dict[str, ProficiencyLevel]]` permits a domain to map either directly to a level or to a sub-dict; the sub-dict cannot itself nest further. Three-level taxonomies are unrepresentable.
- **Person entries are closed at the global overlay boundary.** An undeclared
  key on a `PersonEntry` fails global configuration loading and identifies its
  nested path.
- **Identity vs. preferences are split across files.** A person entry in the global overlay's people list declares who the person is; their `creds`, `notifications`, and `timezone` live in a separate per-person YAML. The global overlay's key-restriction check enforces the split at the global level.
- **`role` enum membership is binding.** Changing the platform's role vocabulary requires a schema migration; operator-defined roles are not representable.
