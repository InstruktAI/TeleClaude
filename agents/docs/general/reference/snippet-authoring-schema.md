---
id: general/reference/snippet-authoring-schema
type: reference
scope: global
description: Schema and section requirements for documentation snippets belonging to a taxonomy.
---

# Snippet Authoring Schema — Reference

## What it is

Defines the required structure and section headings for documentation snippets.

## Canonical fields

- Frontmatter: `id`, `type`, `scope`, `description` (required for non-baseline snippets).
- Title: H1 with type suffix.
- Required reads: H2 `Required reads` with inline `@` references when needed.
- Body: required H2 sections per taxonomy.
- Optional: H2 `See also` for soft references.

## Allowed values

- `type`: policy, standard, guide, procedure, role, checklist, reference, concept, architecture, example, principles.
- `scope`: global, domain, project.
- Procedure sections may include optional: `Pre-completion checklist`, `Report format`.

## Known caveats

- Baseline snippets omit frontmatter but must follow the same section structure.
- Section headings must match the schema exactly; extra headings are invalid.
- Required reads must be acyclic; circular references indicate incorrect information design.
