---
id: 'project/spec/feature/context/third-party-snippet-curation'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
description: 'Curation and indexing of vendor and external reference docs under docs/third-party/ with a separate minimal schema and a parallel Index.'
---

# Third-Party Snippet Curation — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

Third-party snippet curation is the context path that lets the Context
bounded context ingest external reference documentation (vendor docs,
framework references, library guides) under `docs/third-party/` with its own
minimal schema and a dedicated parallel Index, so external Sources sit
alongside taxonomy snippets without polluting the taxonomy frontmatter or
the taxonomy Selection policy.

A third-party snippet is a Markdown file whose Kind is `third-party`. It does
not carry the taxonomy fields (`type` enum, `domain`, `visibility`, `status`,
`delivered_by`). It is keyed by its path-derived ID and a `## Sources` section
that names the Context7 entry, URL, or Markdown link it was distilled from.

## Canonical fields

### Use cases

```
Scenario: Author a third-party snippet under the project tree
  Given a Markdown file at docs/third-party/vendors/acme/widgets.md
  And frontmatter id "third-party/vendors/acme/widgets", type "third-party", scope "project", description "Acme widgets reference"
  And a "## Sources" section listing a Context7 ID and an https URL
  When telec sync runs validation
  Then the file passes third-party validation
  And it is written into the third-party index as an entry with id, description, scope, and path
```

```
Scenario: ID does not match the path
  Given a file at docs/third-party/vendors/acme/widgets.md
  And frontmatter id "third-party/vendors/other/widgets"
  When third-party validation runs
  Then a third-party-id-path-mismatch error is raised against the file
```

```
Scenario: Phase 1 lists third-party entries separately
  Given third-party entries are indexed
  When the operator runs telec docs index --third-party
  Then taxonomy snippets and third-party entries are listed in separate sections
  And the third-party entries show id, description, and scope only
```

```
Scenario: Phase 2 auto-loads third-party indexes on prefix match
  Given the operator requests an ID starting with "third-party/" via telec docs get
  And no --third-party flag was passed
  Then the context selector auto-loads the third-party index
  And the snippet body is returned without a frontmatter header
  And no Required reads dependency expansion is performed for the third-party entry
```

```
Scenario: Description falls back when frontmatter description is empty
  Given a third-party Markdown file with no description in frontmatter
  And a first-line H1 "# Acme Widgets Reference"
  When the third-party index is written
  Then the index entry description is "Acme Widgets Reference"
  And if the H1 is also missing the description falls back to the filename stem
```

### Cross-context references

None direct. Third-party curation is internal to the Context bounded context.

## Known caveats

- Markdown links inside `## Sources` are auto-unwrapped to extract the URL;
  plain URLs and Context7 IDs (`/{scope}/{slug}/...`) are checked as-is.
- Index files (`index.md`, `index.yaml`) under `docs/third-party/` are silently
  skipped by id/source validation so generated artifacts do not self-fail.
- Third-party `scope` is frontmatter-only — the directory placement (project
  tree vs `~/.teleclaude/docs/third-party/`) is NOT cross-checked against the
  declared scope.
- The `.md` version of the third-party index generator is parallel to the
  `.yaml` flow and is a shedding candidate for v2.
- Required reads dependency resolution is never applied to third-party entries
  even if a body uses `@`-style refs — the Selection policy treats third-party
  Sources as terminal leaves.
