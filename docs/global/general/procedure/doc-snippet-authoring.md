---
id: 'general/procedure/doc-snippet-authoring'
type: 'procedure'
scope: 'global'
description: 'Author documentation snippets according to the taxonomy and schema.'
activation_trigger: 'Use when creating or updating documentation snippets'
---

# Snippet Authoring — Procedure

## Required reads

- @~/.teleclaude/docs/general/policy/artifact-scope.md
- @~/.teleclaude/docs/general/principle/priming.md
- @~/.teleclaude/docs/general/principle/intent-first-documentation.md
- @~/.teleclaude/docs/general/policy/referencing-doc-snippets.md
- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Goal

Create a new snippet that conforms to schema and is discoverable by tooling.

## Preconditions

- Snippet taxonomy and schema references available.
- Target docs folder determined.

## Steps

1. Interpret the request through taxonomy: decide the correct type and scope per the artifact-scope policy.
2. Author top-down: broader context should point to narrower details, not the other way around.
3. Add frontmatter (id, type, scope, description). Set `role` if the snippet should be restricted: `admin` for credentials/destructive ops, `public` for public-facing content. Omit for the default `member` level.
4. Write H1 title with correct type suffix.
5. Add Required reads if the snippet depends on other snippets.
6. Add all required sections for the taxonomy type.
7. Organize content inside those valid sections. Use subordinate headings such as `###` when they improve readability; do not flatten useful structure just to avoid internal headings.
8. If validation rejects a heading, first ask whether it should be downgraded under an existing schema section rather than deleted or flattened.
9. After any doc change, run `telec sync` to deploy all artifacts. Commit the regenerated index files as part of the task — they are build outputs of the sync step and reflect the current truth of the docs directory.
10. Do not edit `docs/index.yaml` directly; `telec sync` regenerates it.
11. Avoid creating index.md files; only baseline.md manifests are allowed.

## Outputs

- New or updated snippet with correct structure.
- `telec sync` run after changes.

## Recovery

- If `telec sync` fails, fix the issue and rerun it.
