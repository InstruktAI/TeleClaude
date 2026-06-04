---
id: 'project/spec/feature/config/person-identity-schema'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Per-person identity schema declaring name, validated email, optional username, role enum, nested expertise map, and deprecated single-level proficiency field.'
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
into the global overlay's people list, the only list inside the global config that names
principals; per-person `creds`, `notifications`, and `timezone` live in
separate per-person config files (see the global-level disallowed-keys rule).
Validation strips whitespace from `email` and persists the stripped value, so
downstream consumers can rely on the stored email being canonicalized.

## Canonical fields

### Use cases

#### UC-CFG-PERSON-1: Minimal person entry accepted

```
Given a the global overlay's people list entry { name: "Alice", email: "alice@example.com" }
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
Given a the global overlay's people list entry { name: "Alice", email: "   " }
When email validation runs
Then trimming the value yields the empty string ""
And a validation error is raised with the message: "Person email must be non-empty"
And the global overlay loader raises before save is reachable
```

#### UC-CFG-PERSON-3: Email whitespace is stripped on persist

```
Given a the global overlay's people list entry { name: "Alice", email: "  alice@example.com  " }
When email validation runs
Then trimming the value yields "alice@example.com"
And the validator returns the stripped value
And the stored email is "alice@example.com" (whitespace removed)
```

#### UC-CFG-PERSON-4: min_length=1 on email field rejects empty literal

```
Given a the global overlay's people list entry { name: "Alice", email: "" }
When PersonEntry validation runs
Then the Field(min_length=1) constraint on email fires before validate_email
And validation fails with a string-too-short error
```

#### UC-CFG-PERSON-5: Role enum accepts known values

```
Given a the global overlay's people list entry with role = "admin"
When PersonEntry validation runs
Then the role schema accepts "admin" as a valid role value
And role = "admin"
```

#### UC-CFG-PERSON-6: Role enum rejects unknown values

```
Given a the global overlay's people list entry with role = "owner"
When PersonEntry validation runs
Then the Literal type rejects "owner"
And validation fails with a literal-mismatch error
```

#### UC-CFG-PERSON-7: Flat expertise map accepted

```
Given a the global overlay's people list entry with expertise = {
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
Given a the global overlay's people list entry with expertise = {
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
Given a the global overlay's people list entry with expertise = { "python": "guru" }
When PersonEntry validation runs
Then "guru" is not a member of ProficiencyLevel
And validation fails with a literal-mismatch error
```

#### UC-CFG-PERSON-10: Deprecated `proficiency` field still parses

```
Given a the global overlay's people list entry with proficiency = "intermediate"
When PersonEntry validation runs
Then proficiency accepts the ProficiencyLevel literal "intermediate"
And the entry is accepted
And expertise remains None
```

#### UC-CFG-PERSON-11: Global overlay collects people as a list

```
Given a global overlay YAML with a `people` list of N entries
When global overlay validation runs
Then each entry is independently validated as a person entry
And the global overlay's people list holds the validated person entries
And the empty list is accepted as the default
```

#### UC-CFG-PERSON-12: Global-level disallowed keys are rejected near people

```
Given a global overlay YAML with a top-level `creds` key alongside `people`
When the global overlay's key-restriction check runs
Then `creds` intersects the disallowed set
And a validation error is raised: "Keys not allowed at global level: creds"
And no person-entry parsing is attempted; loading fails first
```

### Cross-context references

- Consumed by the identity bounded context — the principal resolver reads
  the global `people` list to find a principal by name, email, or
  username; the role drives capability gating in the identity context.
- Per-person `creds`, `notifications`, and `timezone` live in the
  per-person config overlay, not on the person entry itself. The entry is
  identity-only; runtime preferences live alongside the person's
  workspace.
- The `config` bounded context (`project/spec/domain/config.md`)
  preserves the person-entry shape; the effective-configuration merge
  keeps the same identity fields exposed to downstream consumers.

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
- **Identity vs. preferences are split across files.** A person entry in the global overlay's people list declares who the person is; their `creds`, `notifications`, and `timezone` live in a separate per-person YAML. The global overlay's key-restriction check enforces the split at the global level.
- **`role` enum membership is binding.** Changing the platform's role vocabulary requires a schema migration; operator-defined roles are not representable.
