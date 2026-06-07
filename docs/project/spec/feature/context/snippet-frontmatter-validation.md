---
id: 'project/spec/feature/context/snippet-frontmatter-validation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Schema, path, ref, and section-shape validation enforced on every taxonomy source snippet during telec sync.'
---

# Snippet Frontmatter Validation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Snippet frontmatter validation is the context gate that runs on every taxonomy
source file during `telec sync` and pre-commit markdown validation. It enforces
the schema of Context snippets so the Index, selection policy, and CRUD
surface never observe broken frontmatter, broken Required reads, wrong IDs,
or wrong taxonomy sections.

Validation is shape-only for lifecycle metadata. `delivered_by`, when
present, must be a non-empty list of slug strings; absence means the snippet
is current. No `status` field is validated or required. Relationship
decisions such as whether a slug exists in the todo list or all slugs have
delivered are owned by lifecycle callers, not by the snippet validator.

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
Scenario: ID does not match path
  Given a snippet at docs/project/spec/feature/context/foo.md
  And frontmatter id "project/spec/feature/context/bar"
  When the id-format and path-derived-id checks run
  Then the path-derived ID mismatch is reported
```

```
Scenario: delivered_by is an empty list
  Given a snippet with an empty delivered_by list
  When validation runs
  Then a "snippet_delivered_by_invalid_shape" finding is reported
```

```
Scenario: delivered_by relationship state is not validated here
  Given a snippet with delivered_by ["future-slug"]
  When snippet frontmatter validation runs
  Then the shape is accepted
  And lifecycle code remains responsible for delivery-time reconciliation
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
  Given a snippet of type "spec" without a "## Canonical fields" H2
  When section-shape validation runs
  Then a missing-section error is reported listing the required H2
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
