---
name: doc-snippet-authoring
description: Author documentation snippets that conform to the taxonomy schema. Use when creating, updating, or reviewing doc snippets for any taxonomy type — principle, concept, policy, procedure, design, spec.
---

# Doc Snippet Authoring

## Required reads

- @~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md

## Purpose

Create or update documentation snippets that conform to the taxonomy schema, are discoverable by `telec docs`, and deploy cleanly via `telec sync`.

## Scope

- All taxonomy types: principle, concept, policy, procedure, design, spec.
- All scopes: global, domain, project.
- Covers snippet creation, structural validation, referencing rules, and deployment.

## Inputs

- Intent: what knowledge to capture and why.
- Taxonomy type and scope (or enough context to determine them).

## Outputs

- A snippet file placed in the correct directory with valid frontmatter, H1 title, and all required sections for its taxonomy type.
- `telec sync` run after changes.

## Procedure

Follow the snippet authoring procedure and schema. Full steps, taxonomy table, directory layout, and referencing rules are in the required reads above.
