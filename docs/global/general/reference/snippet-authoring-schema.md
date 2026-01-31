---
id: general/reference/snippet-authoring-schema
type: reference
scope: global
description: Schema and section requirements for documentation snippets belonging to a taxonomy.
---

# Snippet Authoring Schema — Reference

## What it is

Defines the required structure, section headings, and directory layout for documentation snippets.

## Canonical fields

Frontmatter (required for non-baseline snippets):

- `id` — unique snippet identifier.
- `type` — taxonomy type (see table below).
- `scope` — `global`, `domain`, or `project`.
- `description` — short summary of the snippet's purpose.

Document structure:

- H1 title with type suffix (e.g., `# Session Lifecycle — Architecture`).
- `## Required reads` — immediately after H1, with inline `@` references for hard dependencies. These are expanded (inlined) at build time.
- Required H2 sections per taxonomy (see table below).
- `## Sources` — required for third-party docs, with web links or Context7 snippet IDs.
- `## See also` — optional soft references (not inlined at build time).

### Required H2 sections per taxonomy

| Taxonomy     | Required sections                                                 |
| ------------ | ----------------------------------------------------------------- |
| concept      | What, Why                                                         |
| policy       | Rules, Rationale, Scope, Enforcement, Exceptions                  |
| procedure    | Goal, Preconditions, Steps, Outputs, Recovery                     |
| architecture | Purpose, Inputs/Outputs, Invariants, Primary flows, Failure modes |
| reference    | What it is, Canonical fields, Allowed values, Known caveats       |
| guide        | Goal, Context, Approach, Pitfalls                                 |
| checklist    | Purpose, Preconditions, Checks, Recovery                          |
| role         | Purpose, Responsibilities, Boundaries                             |
| principle    | Principle, Rationale, Implications, Tensions                      |
| example      | Scenario, Steps, Outputs, Notes                                   |

Procedure sections may also include optional: `Pre-completion checklist`, `Report format`.

Architecture snippets should include Mermaid diagrams where visual representation aids understanding. Use flowcharts for data flow, sequence diagrams for interactions, and class diagrams for structural relationships.

### Directory layout

- `docs/global/baseline/{taxonomy}/` — foundational docs, mandatory reading across all domains and projects.
- `docs/global/general/{taxonomy}/` — on-demand cross-domain documentation.
- `docs/global/{domain}/{taxonomy}/` — domain-specific (e.g., `software-development`).
- `docs/project/{taxonomy}/` — project-scoped documentation.

Global snippets are distributed to `~/.teleclaude/docs/` and available to all projects. Project snippets stay local to their repository.

## Allowed values

- `type`: policy, guide, procedure, role, checklist, reference, concept, architecture, example, principle (canonical list in `teleclaude/constants.py:TAXONOMY_TYPES`).
- `scope`: global, domain, project.

## Known caveats

- Baseline snippets omit frontmatter but must follow the same section structure.
- Section headings must match the schema exactly; extra headings are invalid.
- `docs/index.yaml` is auto-generated — never hand-edit it.
