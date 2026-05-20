---
id: 'project/spec/feature/context/snippet-frontmatter-validation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Schema, path, ref, and section-shape validation enforced on every taxonomy source snippet during telec sync.'
---

# Snippet Frontmatter Validation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Snippet frontmatter validation is the v1 gate that runs on every taxonomy
source file during `telec sync`. It enforces the schema of Context snippets so
the Index, the Selection policy, and the CRUD surface never observe broken
frontmatter, broken Required reads, or wrong taxonomy sections.

Validation runs twice per full sync: a first pass before reconciliation (with
`enforce_delivered_drift=False`) and a second pass afterwards (with
`enforce_delivered_drift=True`) so freshly reconciled snippets are re-checked
against the new roadmap state.

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
Scenario: delivered_by references a slug unknown to the roadmap
  Given a snippet with status "target" and delivered_by ["ghost-slug"]
  And the roadmap status map has no entry for "ghost-slug"
  When validation runs
  Then snippet_delivered_by_unknown_slug is reported against "ghost-slug"
```

```
Scenario: delivered_by references a soft-removed slug
  Given a snippet with status "target" and delivered_by ["removed-slug"]
  And the roadmap status map records "removed-slug" as removed
  When validation runs during the trash window
  Then the slug is treated as known
  And it does not count as delivered for unflipped-drift validation
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
Scenario: See Also entry lacks the .md suffix or uses @ refs
  Given a "## See Also" section listing "@docs/foo" instead of "docs/foo.md"
  When validation runs
  Then the See Also formatting error is reported
```

```
Scenario: Per-type required sections missing
  Given a snippet of type "spec" without a "## Canonical fields" H2
  When _validate_snippet_sections runs
  Then a missing-section error is reported listing the required H2
```

```
Scenario: Relative ref with .. parents is unsupported
  Given a Required reads entry "@../other/snippet.md"
  When _resolve_snippet_ref runs
  Then NotImplementedError is raised
```

### Implementation pointers (v1)

- `teleclaude/resource_validation/_snippet.py:69-94` — `resolve_ref_path()`
- `teleclaude/resource_validation/_snippet.py:102-168` — `iter_inline_refs()`, `collect_inline_ref_errors()`
- `teleclaude/resource_validation/_snippet.py:171-181` — `_resolve_snippet_ref()` (raises on `../`)
- `teleclaude/resource_validation/_snippet.py:213-232` — `visibility`, `activation_trigger` enums
- `teleclaude/resource_validation/_snippet.py:265-302` — `_validate_status_and_delivered_by()`
- `teleclaude/resource_validation/_snippet.py:456-552` — See Also + Required reads structural validation
- `teleclaude/resource_validation/_snippet.py:555-607` — `_validate_snippet_sections()`
- `teleclaude/snippet_validation.py:49-105` — `validate_snippet_id_format()`, `expected_snippet_id_for_path()`
- `teleclaude/sync.py:45-49, 77-81` — initial + post-reconcile invocations
- `tools/lint/markdown.py:240` — pre-commit hook invocation

### Cross-context references

- workflow — supplies the roadmap status map consulted when validating
  `delivered_by` slugs.

## Known caveats

- Two validation passes per sync: the initial pass uses
  `enforce_delivered_drift=False`; the post-reconciliation pass uses
  `enforce_delivered_drift=True`.
- The pre-commit lint pipeline calls `validate_all_snippets()` without
  supplying a roadmap status map; `enforce_delivered_drift=True` then applies
  by default, which may flag drift the next full sync would auto-reconcile.
- Soft-removed roadmap slugs are accepted as known `delivered_by` references
  during the trash window, but only delivered slugs count toward
  `snippet_status_unflipped_drift`.
- HTML comments inside `## Required reads` and `## See Also` are silently
  ignored.
- `applies_to` is declared in the typed frontmatter but its path-vs-value
  cross-check is performed elsewhere (lint rule on
  `docs/project/design/architecture*/` paths), not here.
- Validation findings are stdout text grouped by code and reason; consumers
  must parse text — there is no machine-readable output channel in v1.
- `activation_trigger` is allowed only on procedure snippets and is rejected
  on any other taxonomy type.
