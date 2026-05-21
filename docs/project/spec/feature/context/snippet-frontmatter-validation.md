---
id: 'project/spec/feature/context/snippet-frontmatter-validation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'target'
delivered_by: [integrate-deliveredby-flip]
description: 'Schema, path, ref, and section-shape validation enforced on every taxonomy source snippet during telec sync.'
---

# Snippet Frontmatter Validation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Snippet frontmatter validation is the v1 gate that runs on every taxonomy
source file during `telec sync` and pre-commit markdown validation. It enforces
the schema of Context snippets so the Index, selection policy, and CRUD
surface never observe broken frontmatter, broken Required reads, wrong IDs,
or wrong taxonomy sections.

Validation is shape-only for lifecycle metadata. `status: actual` forbids
`delivered_by`; `status: target` and `status: mixed` require a non-empty
`delivered_by` list. Relationship decisions such as whether a slug exists in
the roadmap, whether all slugs have delivered, and when a snippet flips to
actual are owned by lifecycle callers, not by the snippet validator.

## Canonical fields

### Use cases

```
Scenario: Missing required frontmatter field
  Given a snippet file without a "description" key in frontmatter
  When telec sync validates the file
  Then snippet_missing_frontmatter_field is reported for "description"
  And the sync exits with a non-zero status
```

```
Scenario: ID does not match path
  Given a snippet at docs/project/spec/feature/context/foo.md
  And frontmatter id "project/spec/feature/context/bar"
  When validate_snippet_id_format and expected_snippet_id_for_path run
  Then the path-derived ID mismatch is reported
```

```
Scenario: status actual carries delivered_by
  Given a snippet with status "actual" and a non-empty delivered_by list
  When validation runs
  Then snippet_status_actual_forbids_delivered_by is reported
```

```
Scenario: status target missing delivered_by
  Given a snippet with status "target" and no delivered_by key
  When validation runs
  Then snippet_status_target_missing_delivered_by is reported
```

```
Scenario: delivered_by relationship state is not validated here
  Given a snippet with status "target" and delivered_by ["future-slug"]
  When snippet frontmatter validation runs
  Then the shape is accepted
  And lifecycle code remains responsible for delivery-time reconciliation
```

```
Scenario: Required reads is not the first H2
  Given a snippet whose first H2 after H1 is "## What it is"
  And a "## Required reads" H2 appears later
  When validation runs
  Then snippet_required_reads_not_first_h2 is reported
```

```
Scenario: Inline @ ref leaks outside Required reads
  Given a snippet whose "## Canonical fields" body contains "@docs/other.md"
  And the inline @ ref is not inside an inline code span
  When validation runs
  Then snippet_required_reads_outside_section is reported
```

```
Scenario: Per-type required sections missing
  Given a snippet of type "spec" without a "## Canonical fields" H2
  When _validate_snippet_sections runs
  Then a missing-section error is reported listing the required H2
```

### Implementation pointers (v1)

- `teleclaude/resource_validation/_snippet.py` — snippet frontmatter,
  Required reads, See Also, and taxonomy-section validation.
- `teleclaude/snippet_validation.py` — snippet id format and path-derived id
  checks.
- `teleclaude/sync.py` — single-pass validation before index build and
  distribution.
- `tools/lint/markdown.py` — pre-commit hook invocation.

### Cross-context references

- workflow and integration own lifecycle state transitions and delivery-time
  frontmatter reconciliation for `delivered_by`.

## Known caveats

- Validation findings are stdout text grouped by code and reason; consumers
  must parse text because there is no machine-readable output channel in v1.
- HTML comments inside `## Required reads` and `## See Also` are silently
  ignored.
- `applies_to` is declared in typed frontmatter but path-vs-value checks are
  enforced by markdown validation, not by lifecycle reconciliation.
- `activation_trigger` is allowed only on procedure snippets and is rejected
  on any other taxonomy type.
