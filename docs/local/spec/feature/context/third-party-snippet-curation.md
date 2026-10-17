---
description: 'Curation and indexing of vendor and external reference docs under docs/third-party/ with a separate minimal schema and a parallel Index.'
visibility: 'public'
---

# Third-Party Snippet Curation — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

Third-party snippet curation is the context path that lets the Context
bounded context ingest external reference documentation (vendor docs,
framework references, library guides) under `docs/third-party/` with its own
minimal schema and a dedicated parallel Index, so external Sources sit
alongside taxonomy snippets without polluting the taxonomy frontmatter or
the taxonomy Selection policy.

A third-party snippet is a Markdown file placed under `docs/third-party/`. It
does not carry the taxonomy fields (`type` enum, `domain`, `visibility`,
`status`, `delivered_by`), and it no longer authors `id`, `type`, or `scope`
in frontmatter. It is keyed by its path-derived ID, carries an authored
`description`, and a `## Sources` section that names the Context7 entry, URL,
or Markdown link it was distilled from. Its `id` and `scope` are derived from
the path.

## Canonical fields

### Use cases

#### UC-TPSC1: Make a sourced vendor reference available to a project

```gherkin
Scenario: Curate an external reference for project work
  Given a project maintainer needs a vendor or framework reference for the project's work
  When an agent curates that reference for the project
  Then the reference is discoverable separately from taxonomy documentation
  And its originating source is recorded
```

#### UC-TPSC2: Find third-party references separately from taxonomy documents

```gherkin
Scenario: Browse external references
  Given an operator wants to browse available vendor or framework references
  When they open the third-party reference listing
  Then they can distinguish those references from taxonomy documentation
  And each listed reference is described well enough to choose what to retrieve
```

### Cross-context references

None direct. Third-party curation is internal to the Context bounded context.

## Known caveats

- Markdown links inside `## Sources` are auto-unwrapped to extract the URL;
  plain URLs and Context7 IDs (`/{scope}/{slug}/...`) are checked as-is.
- The generated `index.yaml` under `docs/third-party/` is silently skipped by
  id/source validation so the index artifact does not self-fail.
- Third-party `scope` is path-derived from the directory placement (project
  tree vs `~/.teleclaude/docs/third-party/`); it is no longer authored in
  frontmatter.
- Required reads dependency resolution is never applied to third-party entries
  even if a body uses `@`-style refs — the Selection policy treats third-party
  Sources as terminal leaves.
