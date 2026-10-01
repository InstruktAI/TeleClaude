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
<!-- planned-change:tier-validation-misses-authored-scope -->
`id`/`type`/`scope` are path-derived and are no longer authored or validated, so
there is no id-to-path check.
<!-- change:tier-validation-misses-authored-scope -->
`id`/`type`/`scope`/`domain` are path-derived and never authored, so there is no
id-to-path check. A person or company tier source that authors any of them
receives a finding naming each authored field.
<!-- /planned-change:tier-validation-misses-authored-scope -->

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

```
Scenario: Missing required frontmatter field
  Given a snippet file without a "description" key in frontmatter
  When source validation runs over the file
  Then a missing-frontmatter-field finding is reported for "description"
  And validation exits with a non-zero status
```

```
Scenario: delivered_by is an empty list
  Given a snippet with an empty delivered_by list
  When validation runs
  Then a "snippet_delivered_by_invalid_shape" finding is reported
```

```
Scenario: delivered_by relationship state is validated on a full run
  Given a snippet with delivered_by ["already-delivered-slug"]
  And the todos DB is reachable (full run)
  And the checkout contains that todo's delivery commit
  When snippet validation runs
  Then a "snippet_delivered_by_invalid_slug" finding is reported
Scenario: delivered_by naming a delivered todo whose delivery commit the checkout lacks is tolerated
  Given a snippet with delivered_by ["already-delivered-slug"]
  And the todos DB is reachable (full run)
  And the checkout does not contain that todo's delivery commit
  When snippet validation runs
  Then no relationship finding is reported
Scenario: delivered_by naming a delivered todo with no recorded delivery commit is tolerated
  Given a snippet with delivered_by ["already-delivered-slug"]
  And the todos DB records no delivery commit for that todo
  When snippet validation runs
  Then no relationship finding is reported
Scenario: delivered_by naming a soft-removed todo is tolerated
  Given a snippet with delivered_by ["removed-slug"]
  And the todos DB reports "removed-slug" as removed (full run)
  When snippet validation runs
  Then no relationship finding is reported
Scenario: delivered_by naming a slug absent from the local store is tolerated
  Given a snippet with delivered_by ["unknown-slug"]
  And the todos DB has no todo "unknown-slug" (full run)
  When snippet validation runs
  Then no relationship finding is reported
Scenario: delivered_by relationship state is not checked on a scoped run
  Given a snippet with delivered_by ["already-delivered-slug"]
  And validation runs per-file without the todos DB
  When snippet validation runs
  Then the shape is accepted and no relationship finding is reported
```

#### UC-SFV1: Planned-change marker shape is validated mechanically

```
Given a snippet contains a planned-change block with matching open, change, and close markers
When snippet validation runs
Then no planned-change marker finding is reported
Given a snippet contains a planned-change block with a missing close marker, mismatched slug, or missing change separator
When snippet validation runs
Then a planned-change marker finding is reported
```

#### UC-SFV1b: In-body marker slug liveness is validated on full runs

```
Given a snippet contains an in-body planned or planned-change marker whose slug resolves to a delivered todo
And the todos DB is reachable (full run)
And the checkout contains that todo's delivery commit
When snippet validation runs
Then a "snippet_planned_marker_invalid_slug" finding is reported for that slug
Given the marker slug resolves to a delivered todo whose delivery commit the checkout does not contain, or whose delivery commit is unrecorded
When snippet validation runs
Then no marker-liveness finding is reported
Given the marker slug resolves to a retained todo (active, icebox, or soft-removed), or names no todo in the local store
When snippet validation runs
Then no marker-liveness finding is reported
Given the marker appears only inside an inline code span or a fenced code block (a syntax example)
When snippet validation runs
Then no marker-liveness finding is reported
Given validation runs per-file or without a reachable todos DB
When snippet validation runs
Then marker-liveness is not checked
```

#### UC-SFV1c: In-body markers must be whole-line, non-nested, and balanced

```
Given a snippet contains a planned, planned-change, or change marker with non-whitespace text before its opening "<!--" or after its closing "-->" on the same line
When snippet validation runs
Then a "snippet_marker_not_line_level" finding is reported for that marker
Given a snippet contains an in-body block whose markers each occupy their own line, is balanced, and no other slug's marker opens between its open and close
When snippet validation runs
Then no line-level, balance, or nesting finding is reported
Given a snippet contains a planned ADD opening marker with no matching close, a close with no matching open, or a close whose slug differs from the open
When snippet validation runs
Then a "snippet_marker_unbalanced" finding is reported for that marker
Given a snippet contains an in-body block (planned or planned-change) that opens while another in-body block is still open
When snippet validation runs
Then a "snippet_marker_nested" finding is reported for the inner marker
Given a snippet contains a planned ADD block whose opening marker is never closed, or a planned close marker with no matching open, or a planned close whose slug differs from its open
When snippet validation runs
Then a "snippet_marker_unbalanced" finding is reported for the unbalanced marker
Given a snippet contains a planned ADD marker whose slug is not kebab-case
When snippet validation runs
Then a "snippet_marker_invalid_slug" finding is reported for that marker
Given the marker appears only inside an inline code span or a fenced code block (a syntax example)
When snippet validation runs
Then no line-level, balance, or nesting finding is reported
```

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

```
Given a procedure snippet declares both the events that activate it and a self-selection activation trigger
When snippet validation runs
Then an activation-mode conflict finding is reported for that file
And the sync exits with a non-zero status
Given a procedure snippet declares only the events that activate it
When snippet validation runs
Then no activation-mode finding is reported
Given a procedure snippet declares only a self-selection activation trigger
When snippet validation runs
Then no activation-mode finding is reported
Given a procedure snippet declares neither activation mode
When snippet validation runs
Then no activation-mode finding is reported
```

#### UC-SFV4: Only a procedure published where subscriptions are routed may declare them

```
<!-- planned-change:procedure-activation-gated-on-company -->
Given a procedure snippet published in the global tier or in a company's tier declares the events that activate it
<!-- change:procedure-activation-gated-on-company -->
Given a procedure snippet published in the global tier, in a company's tier, or in a person's tier declares the events that activate it
<!-- /planned-change:procedure-activation-gated-on-company -->
When snippet validation runs
Then no subscription-tier finding is reported
Given a procedure snippet published in any other tier declares the events that activate it
When snippet validation runs
Then a subscription-tier finding is reported for that file, naming its tier
And the sync exits with a non-zero status
```

#### UC-SFV5: An empty companion is accepted as a retirement

```
Given an agent commits a zero-byte sibling companion naming a slug beside a live snippet
When snippet validation runs on that commit
Then the agent receives no frontmatter, title-suffix, or section finding for the companion
And the live snippet is still validated in full
```

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
<!-- planned-change:tier-validation-misses-authored-scope -->
- `id`/`type`/`scope` are no longer authored or validated — they are derived
  from the Source's path, so no id-to-path mismatch check exists.
<!-- change:tier-validation-misses-authored-scope -->
- `id`/`type`/`scope`/`domain` are derived from the Source's path, so no
  id-to-path mismatch check exists. An authored classification field is
  reported only on a person or company tier source; a project or global source
  that authors one is accepted and the index build ignores the authored value.
<!-- /planned-change:tier-validation-misses-authored-scope -->

## See Also

- docs/local/spec/feature/context/lifecycle-marker-reconciliation.md — the owner of the delivery fold, which performs the marker removal as part of the delivery commit.
