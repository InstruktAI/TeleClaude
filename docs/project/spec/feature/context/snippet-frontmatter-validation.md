---
description: Schema, path, ref, and section-shape validation enforced on every taxonomy
  source snippet during telec sync.
visibility: public
---

# Snippet Frontmatter Validation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Snippet frontmatter validation is the context gate that runs on every taxonomy
source file during `telec sync` and pre-commit markdown validation. It enforces
the schema of Context snippets so the Index, selection policy, and CRUD
surface never observe broken frontmatter, broken Required reads, leaked inline
refs, wrong H1 type suffixes, or wrong taxonomy sections. Validation enforces
presence of the authored `description`, correct Required-reads placement,
inline-ref scoping, H1 type-suffix consistency, and per-type section shape —
where the type is derived from the path, not from frontmatter.
`id`/`type`/`scope` are path-derived and are no longer authored or validated, so
there is no id-to-path check.

Frontmatter shape is always validated: `delivered_by`, when present, must be a
non-empty list of slug strings; absence means the snippet is current. No
`status` field is validated or required. On a full `telec sync` run with the
todos DB reachable, relationship state is additionally validated against the
**local** todos store: every `delivered_by` slug and every in-body planned /
planned-change marker slug is checked. A slug resolving to a retained todo —
active, icebox, or soft-removed — is tolerated. A slug that names **no todo in
the local store is expected and not reported**: todos are machine-local, so a
snippet carried in git routinely references an in-flight todo that lives on
another computer, or one already hard-purged with its markers folded by
maintenance. Only a slug resolving to a **delivered** todo is reported — a
marker that delivery should have folded but did not. Scoped per-file runs and
runs without a reachable todos DB validate shape only.

## Canonical fields

### Use cases

```
Scenario: Missing required frontmatter field
  Given a snippet file without a "description" key in frontmatter
  When telec sync validates the file
  Then a missing-frontmatter-field finding is reported for "description"
  And the sync exits with a non-zero status
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
  When snippet validation runs
  Then a "snippet_delivered_by_invalid_slug" finding is reported
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
When snippet validation runs
Then a "snippet_planned_marker_invalid_slug" finding is reported for that slug
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

<!-- planned:code-uc-blueprint-traceability -->
#### UC-SFV3: Published use-case identities are unique in the effective corpus

```gherkin
Given the global and project specifications visible to the invoking project contain use-case headings
When snippet validation builds the effective use-case catalog
Then each identity and effective revision resolves to exactly one defining specification
And a duplicate identity, malformed revision, or conflicting revision is reported with every authored location
And identities in another project's non-visible specification corpus are outside this validation boundary
```
<!-- /planned:code-uc-blueprint-traceability -->

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
- `id`/`type`/`scope` are no longer authored or validated — they are derived
  from the Source's path, so no id-to-path mismatch check exists.
