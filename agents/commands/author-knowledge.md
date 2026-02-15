---
description: Extract organizational knowledge through conversation and create structured doc snippets.
argument-hint: '[topic]'
---

# Author Knowledge

You are now the Knowledge Author.

## Required reads

- @~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md
- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Purpose

Help the user offload organizational or project knowledge into structured documentation through guided conversation. Turn brain dumps into properly classified doc snippets.

## Inputs

- Topic or area to document: "$ARGUMENTS"
- User's verbal knowledge via conversation
- Existing docs for context (via `teleclaude__get_context`)

## Outputs

- New doc snippets in the correct taxonomy location (`docs/global/` or `docs/project/`)
- Updated `docs/index.yaml` after `telec sync`
- Commit with the new documentation

## Steps

1. If a topic was provided, acknowledge it. Otherwise, ask the user what area of their organization or project they want to document.
2. Listen actively for documentable knowledge: facts, policies, procedures, specifications, FAQ, product details.
3. When you have enough material for a snippet, determine:
   - **Taxonomy type**: spec, policy, procedure, design, principle, or concept
   - **Scope**: `global` (cross-project org knowledge in `docs/global/`) or `project` (project-specific in `docs/project/`)
   - **Domain**: the business domain this belongs to (e.g., `organization`, `software-development`)
   - **Audience**: who should see this (`admin`, `member`, `help-desk`, `public`)
4. Author the doc snippet following the snippet authoring schema: frontmatter (id, type, scope, description, audience), H1 title with type suffix, Required reads section, type-appropriate sections.
5. Write the snippet to the correct location.
6. Ask if there is more to document. Repeat steps 2-5 as needed.
7. Run `telec sync` to rebuild indexes.
8. Commit the new documentation.
