---
id: 'project/spec/feature/context/lifecycle-marker-reconciliation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Sync-time flip of status target or mixed snippets to actual when all delivered_by slugs reach roadmap status delivered.'
---

# Lifecycle Marker Reconciliation — Spec

## Required reads

- @docs/project/spec/domain/context.md
- @docs/project/spec/feature/context/snippet-frontmatter-validation.md

## What it is

Lifecycle marker reconciliation is the v1 sync-time pass that keeps the
documentation-first discipline honest. When a snippet is authored ahead of
implementation it is marked `status: target` (or `status: mixed`) with a
`delivered_by` list of roadmap slugs. As those slugs reach `delivered` in the
roadmap, reconciliation rewrites the snippet metadata so the Index reflects
what the system actually does today.

The pass is part of full `telec sync` only. `--validate-only` skips it
entirely, and pre-commit lint paths usually run without a roadmap status map
so they observe but do not flip.

## Canonical fields

### Use cases

```
Scenario: All delivered_by slugs are delivered
  Given a snippet with status "target" and delivered_by ["alpha", "beta"]
  And the roadmap status map reports both slugs as "delivered"
  When reconcile_snippet_status runs during telec sync
  Then status and delivered_by are removed from frontmatter
  And the file is rewritten in place with clean YAML frontmatter
```

```
Scenario: Some delivered_by slugs are still pending
  Given a snippet with status "mixed" and delivered_by ["alpha", "beta"]
  And the roadmap status map reports "alpha" delivered and "beta" pending
  When reconciliation runs
  Then delivered_by is rewritten to ["beta"]
  And status remains "mixed"
```

```
Scenario: Validate-only sync skips reconciliation
  Given the operator runs telec sync --validate-only
  And one snippet would otherwise flip from target to actual
  When sync completes
  Then no snippet file is rewritten
  And the would-be drift surfaces as a validation finding only
```

```
Scenario: Post-reconcile drift detection
  Given a snippet whose delivered_by was all-delivered before sync
  And reconciliation failed to rewrite the file for any reason
  When the second validation pass runs with enforce_delivered_drift True
  Then snippet_status_unflipped_drift is reported
```

```
Scenario: Slug delivered during the sync run
  Given a roadmap status map loaded at sync start
  And a slug transitions to "delivered" after the map was loaded
  When reconciliation runs in this sync
  Then the affected snippets are NOT flipped this run
  And the next telec sync picks up the change
```

```
Scenario: Unknown delivered_by slug
  Given a snippet whose delivered_by contains a slug missing from the roadmap
  When reconciliation runs
  Then the unknown slug is treated as "not delivered"
  And the validation pass reports snippet_delivered_by_unknown_slug separately
```

### Implementation pointers (v1)

- `teleclaude/docs_reconcile.py:42` — roadmap status map load
- `teleclaude/docs_reconcile.py:57-61` — `_render_frontmatter()` rewrite
- `teleclaude/docs_reconcile.py:76-83` — `_delivered_by()` extraction
- `teleclaude/docs_reconcile.py:86-127` — `_reconciled_metadata()`,
  `reconcile_snippet_status()` (flip + cleanup logic)
- `teleclaude/resource_validation/_snippet.py:235-262` —
  `build_roadmap_status_map()`
- `teleclaude/resource_validation/_snippet.py:302` —
  `snippet_status_unflipped_drift` code
- `teleclaude/sync.py:42, 68, 77-81` — load → reconcile → re-validate sequence

### Cross-context references

- workflow — the `delivered` roadmap status is the trigger for every flip;
  the status map is sourced from `.teleclaude/todos.db`.

## Known caveats

- Reconciliation runs once per full sync; if a slug delivers mid-sync the
  affected snippets do not flip until the next sync invocation.
- The roadmap status map is point-in-time; subsequent slug deliveries during
  the same process do not retroactively flip already-loaded snippets.
- `applies_to` is declared on the typed frontmatter but is neither read nor
  rewritten by reconciliation — migration cohort markers are stable across
  flips.
- Lint runs (pre-commit) typically do NOT reconcile; full `telec sync` is the
  only reconciler. A snippet that would have flipped may therefore appear as
  drift during lint and disappear after the next sync.
- The flip collapses to implicit `actual` by removing `status` and
  `delivered_by` entirely rather than writing `status: actual` explicitly.
