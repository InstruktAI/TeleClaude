---
id: project/spec/feature/config/person-identity-schema
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Per-person identity schema declaring name, validated email, optional username, role enum, nested expertise map, and deprecated single-level proficiency field.
---

# Person Identity Schema — Spec

## Required reads

- @docs/project/spec/domain/config.md

## What it is

A `PersonEntry` declares the identity of a human principal in the platform's
global configuration. v1 keeps the schema deliberately narrow: a required
`name`, a required and stripped-non-empty `email`, an optional Telegram-style
`username`, a `role` chosen from a closed enum
(`admin | member | contributor | newcomer`, default `member`), and a nested
`expertise` map that captures domain proficiency at one or two levels. The
single-level `proficiency` field is preserved on the model for backward
compatibility but is deprecated in favor of `expertise`. Entries are collected
into `GlobalConfig.people`, the only list inside the global config that names
principals; per-person `creds`, `notifications`, and `timezone` live in
separate per-person config files (see the global-level disallowed-keys rule).
Validation strips whitespace from `email` and persists the stripped value, so
downstream consumers can rely on the stored email being canonicalized.

## Canonical fields

### Use cases

#### UC-CFG-PERSON-1: Minimal person entry accepted

```
Given a GlobalConfig.people entry { name: "Alice", email: "alice@example.com" }
When PersonEntry validation runs
Then validate_email strips and finds the value non-empty
And the stripped value "alice@example.com" is stored on the model
And username defaults to None
And role defaults to "member"
And expertise defaults to None
And proficiency defaults to None
```

#### UC-CFG-PERSON-2: Empty email rejected before storage

```
Given a GlobalConfig.people entry { name: "Alice", email: "   " }
When PersonEntry.validate_email runs
Then v.strip() yields the empty string ""
And a ValueError is raised with the message: "Person email must be non-empty"
And load_global_config raises before save is reachable
```

#### UC-CFG-PERSON-3: Email whitespace is stripped on persist

```
Given a GlobalConfig.people entry { name: "Alice", email: "  alice@example.com  " }
When PersonEntry.validate_email runs
Then v.strip() yields "alice@example.com"
And the validator returns the stripped value
And the stored PersonEntry.email is "alice@example.com" (whitespace removed)
```

#### UC-CFG-PERSON-4: min_length=1 on email field rejects empty literal

```
Given a GlobalConfig.people entry { name: "Alice", email: "" }
When PersonEntry validation runs
Then the Field(min_length=1) constraint on email fires before validate_email
And validation fails with a string-too-short error
```

#### UC-CFG-PERSON-5: Role enum accepts known values

```
Given a GlobalConfig.people entry with role = "admin"
When PersonEntry validation runs
Then the Literal["admin", "member", "contributor", "newcomer"] type accepts "admin"
And role = "admin"
```

#### UC-CFG-PERSON-6: Role enum rejects unknown values

```
Given a GlobalConfig.people entry with role = "owner"
When PersonEntry validation runs
Then the Literal type rejects "owner"
And validation fails with a literal-mismatch error
```

#### UC-CFG-PERSON-7: Flat expertise map accepted

```
Given a GlobalConfig.people entry with expertise = {
  "python": "expert",
  "design": "intermediate"
}
When PersonEntry validation runs
Then expertise is a dict mapping each domain to a ProficiencyLevel literal
And each value is one of "novice" | "intermediate" | "advanced" | "expert"
And the entry is accepted
```

#### UC-CFG-PERSON-8: Nested expertise map accepted

```
Given a GlobalConfig.people entry with expertise = {
  "software-development": { "python": "expert", "rust": "intermediate" },
  "design": "advanced"
}
When PersonEntry validation runs
Then expertise accepts both shapes per the type
  dict[str, ProficiencyLevel | dict[str, ProficiencyLevel]]
And the entry is accepted with mixed flat-and-nested values
```

#### UC-CFG-PERSON-9: Expertise with unknown proficiency level rejected

```
Given a GlobalConfig.people entry with expertise = { "python": "guru" }
When PersonEntry validation runs
Then "guru" is not a member of ProficiencyLevel
And validation fails with a literal-mismatch error
```

#### UC-CFG-PERSON-10: Deprecated `proficiency` field still parses

```
Given a GlobalConfig.people entry with proficiency = "intermediate"
When PersonEntry validation runs
Then proficiency accepts the ProficiencyLevel literal "intermediate"
And the entry is accepted
And expertise remains None
```

#### UC-CFG-PERSON-11: GlobalConfig collects people as a list

```
Given a GlobalConfig YAML with a `people` list of N entries
When GlobalConfig validation runs
Then each entry is independently validated as a PersonEntry
And GlobalConfig.people is the list of validated PersonEntry instances
And the empty list is accepted as the default
```

#### UC-CFG-PERSON-12: Global-level disallowed keys are rejected near people

```
Given a GlobalConfig YAML with a top-level `creds` key alongside `people`
When GlobalConfig.reject_disallowed_keys runs
Then `creds` intersects the disallowed set
And a ValueError is raised: "Keys not allowed at global level: creds"
And no PersonEntry parsing is attempted; loading fails first
```

### Implementation pointers (v1)

- `teleclaude/config/schema.py:144` — `ProficiencyLevel` literal definition (`"novice" | "intermediate" | "advanced" | "expert"`).
- `teleclaude/config/schema.py:147-165` — `PersonEntry` model with fields, `validate_email` validator, and deprecated `proficiency` field.
- `teleclaude/config/schema.py:355-359` — `GlobalConfig.people: list[PersonEntry] = []`.
- `teleclaude/config/schema.py:385-395` — `GlobalConfig.reject_disallowed_keys` that blocks per-person fields from leaking into the global file alongside `people`.

### Cross-context references

- Consumed by `identity` (`teleclaude/core/identity.py`) — the principal
  resolver reads `GlobalConfig.people` to find a principal by name, email, or
  username; the role drives capability gating in the identity bounded context.
- Per-person `creds`, `notifications`, and `timezone` live in
  `PersonConfig` (one YAML per person under `~/.teleclaude/people/<name>/`),
  not on `PersonEntry`. `PersonEntry` is identity-only; runtime preferences
  live alongside the person's workspace.
- The v2 `config` bounded context (see `docs/project/spec/domain/config.md`)
  preserves the PersonEntry shape; the v2 effective-configuration merge keeps
  the same identity fields exposed to downstream consumers.

## Allowed values

- `name` — non-empty string. Required.
- `email` — string, stripped, non-empty after strip. Required. `Field(min_length=1)` rejects an empty literal before the validator runs.
- `username` — optional string. Default: `None`.
- `role` — `"admin" | "member" | "contributor" | "newcomer"`. Default: `"member"`.
- `expertise` — optional `dict[str, ProficiencyLevel | dict[str, ProficiencyLevel]]`. Default: `None`.
- `proficiency` — optional `ProficiencyLevel`. **Deprecated** — use `expertise` instead. Default: `None`.

## Known caveats

- **No format validation on `email`.** The validator only enforces non-emptiness after strip; any non-empty string passes (no `@` requirement, no domain validation). Consumers receive whatever the operator wrote, minus surrounding whitespace.
- **`name` is unique by convention, not by schema.** Two `PersonEntry` rows with the same `name` are both accepted; downstream resolution must decide how to disambiguate.
- **`proficiency` and `expertise` are not jointly validated.** A `PersonEntry` may carry both fields at once; the schema accepts the combination without warning. Consumers choosing to honor `expertise` over `proficiency` must implement that preference themselves.
- **Expertise nesting depth is fixed at two.** The type `dict[str, ProficiencyLevel | dict[str, ProficiencyLevel]]` permits a domain to map either directly to a level or to a sub-dict; the sub-dict cannot itself nest further. Three-level taxonomies are unrepresentable.
- **`extra="allow"` admits unknown keys.** Additional YAML keys on a `PersonEntry` land on the model silently; typos in field names will not fail validation.
- **Identity vs. preferences are split across files.** The `PersonEntry` row in `GlobalConfig.people` declares who the person is; their `creds`, `notifications`, and `timezone` live in a separate per-person YAML. The `reject_disallowed_keys` validator on `GlobalConfig` enforces the split at the global level.
- **`role` enum membership is binding.** Changing the platform's role vocabulary requires a schema migration; operator-defined roles are not representable.
