---
description: Schema, path, ref, and section-shape validation enforced on every taxonomy
  source snippet during source validation.
visibility: public
---

# Snippet Frontmatter Validation — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

Snippet frontmatter validation is the context gate that runs on every taxonomy
source file during source validation and the pre-commit markdown gate. It enforces
the schema of Context snippets so the Index, selection policy, and CRUD
surface never observe broken frontmatter, broken Required reads, leaked inline
refs, wrong H1 type suffixes, or wrong taxonomy sections. Validation enforces
presence of the authored `description`, correct Required-reads placement,
inline-ref scoping, H1 type-suffix consistency, and per-type section shape —
where the type is derived from the path, not from frontmatter.
`id`/`type`/`scope`/`domain` are path-derived and never authored, so there is no
id-to-path check. A person or company tier source that authors any of them
receives a finding naming each authored field.

A Required read or inline reference whose address is well-formed but names a
domain that no project registered on this computer publishes is reported with
config's refusal for that domain
(`local/projects/teleclaude/spec/feature/config/referent-resolution`), never as
a malformed reference; the snippet carrying it is otherwise validated in full.

Frontmatter shape is always validated: `delivered_by`, when present, must be a
non-empty list of slug strings; absence means the snippet is current. No
`status` field is validated or required. When publication runs with the
todos DB reachable, relationship state is additionally validated against the
**local** todos store: every `delivered_by` slug and every in-body planned /
planned-change marker slug is checked. A slug resolving to a retained todo —
active, icebox, or soft-removed — is tolerated. A slug that names **no todo in
the local store is expected and not reported**: todos are machine-local, so a
snippet carried in git routinely references an in-flight todo that lives on
another computer, or one already hard-purged with its markers folded by
maintenance. A slug resolving to a **delivered** todo is reported only when the
validated checkout contains that todo's delivery commit. A delivered todo whose
delivery commit is unrecorded is not reported. Scoped per-file runs and runs
without a reachable todos DB validate shape only.

## Canonical fields

### Use cases

#### UC-SFV1: Planned-change marker shape is validated mechanically

#### UC-SFV1b: In-body marker slug liveness is validated on full runs

#### UC-SFV1c: In-body markers must be whole-line, non-nested, and balanced

#### UC-SFV2: H1 type suffix is validated from the path-derived type

```
Given a taxonomy snippet whose path-derived type is "policy"
And its H1 does not end with "— Policy"
When snippet validation runs
Then a snippet_title_suffix_invalid finding is reported for that file
Given the same taxonomy snippet's H1 ends with "— Policy"
When snippet validation runs
Then no title-suffix finding is reported
Given a pending companion for a policy snippet
When snippet validation runs on the companion
Then the required H1 suffix is still derived from the parent policy path
```

```
Scenario: Required reads is not the first H2
  Given a snippet whose first H2 after H1 is "## What it is"
  And a "## Required reads" H2 appears later
  When validation runs
  Then a "Required reads not first H2" finding is reported
```

```
Scenario: Inline @ ref leaks outside Required reads
  Given a snippet whose "## Canonical fields" body contains "@docs/other.md"
  And the inline @ ref is not inside an inline code span
  When validation runs
  Then a "Required reads outside section" finding is reported
```

```
Scenario: Per-type required sections missing
  Given a snippet whose path-derived type is "spec" without a "## Canonical fields" H2
  When section-shape validation runs
  Then a missing-section error is reported listing the required H2
```

#### UC-SFV3: A procedure declares one activation mode, never two

#### UC-SFV4: Only a procedure published where subscriptions are routed may declare them

#### UC-SFV5: An empty companion is accepted as a retirement

#### UC-SFV6: A subscribed procedure declares the one home kind it answers

#### UC-SFV7: A subscription is a type pattern

#### UC-SFV8: A subscribed procedure may declare which agent answers each event

#### UC-SFV9: A subscribed procedure may declare that no person watches its agent

#### UC-SFV10:

Publication resolves the declaration defaults and publishes the effective
delivery settings alongside the existing subscription facts. Field names,
values and defaults are owned by `general/spec/snippet-authoring-schema`;
interpretation uses the same resolved declaration for publication and activation
routing. Required reads are authored references resolved by the context's
ordinary dependency contract (`sdlc/principle/design-fundamentals`).

#### UC-SFV11: A procedure's role declaration names a catalog role

#### UC-SFV12: A procedure's parameters are well-formed

#### UC-SFV13: A procedure's dispatch defaults are well-formed

### Cross-context references

- workflow and integration own lifecycle state transitions and delivery-time
  frontmatter reconciliation for `delivered_by`.

## Known caveats

- Validation findings are stdout text grouped by code and reason; consumers
  must parse text because there is no machine-readable output channel today.
- HTML comments inside `## Required reads` and `## See Also` are silently
  ignored.
- `activation_trigger` is allowed only on procedure snippets and is rejected
  on any other taxonomy type.
- `id`/`type`/`scope`/`domain` are derived from the Source's path, so no
  id-to-path mismatch check exists. Validation detects an authored
  classification field only on a person or company tier source; on a project or
  global source it goes unreported, and the index build derives the field from
  the path regardless.

## See Also

- docs/local/spec/feature/context/lifecycle-marker-reconciliation.md — the owner of the delivery fold, which performs the marker removal as part of the delivery commit.
