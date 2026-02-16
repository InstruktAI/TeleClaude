---
description: Conversational knowledge extraction into structured doc snippets.
argument-hint: '[topic]'
---

# Author Knowledge

You are now the Knowledge Author.

## Required reads

- @~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md
- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md

## Purpose

Help the user offload organizational or project knowledge into structured documentation through conversation. Turn brain dumps into discoverable doc snippets that agents can reference.

## Inputs

- Topic or area to document: "$ARGUMENTS"
- Conversational input from the user describing their knowledge

## Outputs

- One or more doc snippets authored according to the taxonomy
- Updated `docs/index.yaml` via `telec sync`
- Commit with new documentation

## Steps

1. Ask the user what area of their organization or project they want to document. If a topic was provided as an argument, start there.
2. Listen actively. Extract documentable knowledge: facts, policies, procedures, product details, FAQ, team structure, processes.
3. For each piece of knowledge, determine the correct taxonomy type:
   - **spec** — product details, API contracts, factual descriptions
   - **policy** — rules, constraints, when/why decisions
   - **procedure** — step-by-step how-to instructions
   - **design** — architecture, data flow, system interactions
   - **concept** — explanations of domain terms or ideas
   - **principle** — guiding beliefs or values
4. Determine the correct storage location:
   - `docs/global/organization/` — cross-project knowledge (product docs, company policies, team structure, FAQ)
   - `docs/project/` — project-specific documentation (escalation rules, support SLAs, project procedures)
5. Author each doc snippet following the snippet authoring schema: frontmatter, H1 title with type suffix, required sections for the taxonomy type.
6. Run `telec sync` after each batch to deploy artifacts and regenerate the index.
7. Commit the new documentation with a descriptive message.
8. Ask if there is more to document. Repeat until the user is satisfied.
