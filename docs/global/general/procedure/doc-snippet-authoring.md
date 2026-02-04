---
id: general/procedure/doc-snippet-authoring
type: procedure
scope: global
description: Author documentation snippets according to the taxonomy and schema.
---

# Snippet Authoring — Procedure

## Required reads

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

1. Interpret the request through taxonomy: decide the correct type and scope.
2. Author top-down: broader context should point to narrower details, not the other way around.
3. Add frontmatter (id, type, scope, description).
4. Write H1 title with correct type suffix.
5. Add Required reads if the snippet depends on other snippets.
6. Add all required sections for the taxonomy type.
7. After any doc change, run `telec sync` to deploy all artifacts.
8. Do not edit `docs/index.yaml` directly; `telec sync` regenerates it.
9. Avoid creating index.md files; only baseline index.md is allowed and auto-generated.

## Outputs

- New or updated snippet with correct structure.
- `telec sync` run after changes.

## Recovery

- If `telec sync` fails, fix the issue and rerun it.
