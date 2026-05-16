---
id: 'general/spec/snippet-authoring-schema'
type: 'spec'
scope: 'global'
description: 'Schema and section requirements for documentation snippets belonging to a taxonomy.'
---

# Snippet Authoring Schema — Spec

## What it is

Defines the required structure, section headings, and directory layout for documentation snippets.

## Canonical fields

Frontmatter (required for all snippets):

- `id` — unique snippet identifier.
- `type` — taxonomy type (see table below).
- `domain` — knowledge domain (e.g., `software-development`, `general`). Derived from the directory path.
- `scope` — `global`, `domain`, or `project`.
- `description` — short summary of the snippet's purpose.

Frontmatter (optional):

- `visibility` — access classification: `public` or `internal`. Defaults to `internal` when omitted. Admin callers see all snippets; non-admin callers see only `public` snippets.
- `activation_trigger` — procedures only. A non-empty string describing when to activate the procedure. Appears in the "Activatable Procedures" section of generated AGENTS.md for progressive disclosure. Validation rejects this field on non-procedure snippet types.

Third-party docs under `docs/third-party/` or `~/.teleclaude/docs/third-party/` are indexed separately from taxonomy snippets. They still require `id`, `type`, `scope`, and `description`, but use `type: third-party`, `scope: project` or `scope: global`, and IDs derived from their path below the third-party root.

Document structure:

- H1 title with type suffix (e.g., `# Session Lifecycle — Design`).
- `## Required reads` — immediately after H1, with inline `@` references for hard dependencies. These are expanded (inlined) at build time.
- Required H2 sections per taxonomy (see table below).
- Additional structure inside valid sections is allowed. Use subordinate headings such as `###` when they improve clarity; schema validation constrains the required H2 section names, not the internal organization within them.
- `## Sources` — third-party docs may include web links or Context7 snippet IDs when authoritative references are available.
- `## See Also` — optional soft references (not inlined at build time).

### Required H2 sections per taxonomy

| Taxonomy  | Required sections                                                      |
| --------- | ---------------------------------------------------------------------- |
| principle | Principle, Rationale, Implications, Tensions                           |
| concept   | What, Why                                                              |
| policy    | Rules, Rationale, Scope, Enforcement, Exceptions                       |
| procedure | Goal, Preconditions, Steps, Outputs, Recovery                          |
| design    | Purpose, Inputs/Outputs, Invariants, Primary flows, Failure modes      |
| spec      | What it is, Canonical fields (optional: Allowed values, Known caveats) |

Procedure sections may also include optional: `Pre-completion checklist`, `Report format`, `Required tools`, `Discipline`.

The `Discipline` section is the behavioral anchor — 3–5 sentences naming the specific failure mode this procedure guards against. Commands are thin wrappers that delegate to their procedure's discipline (`Follow the <procedure>'s discipline.`); the section must live on the procedure so the delegation resolves.

The `Required tools` section lists `telec` commands the agent must use during this procedure. Commands listed here are mandatory — agents must not improvise alternatives (direct file reads, custom scripts). Each entry is a concrete command pattern. Globally expanded commands (available to all agents via the CLI surface) are listed by their top-level signature. Procedure-scoped commands are listed with full invocation patterns.

Design snippets should include Mermaid diagrams where visual representation aids understanding. Use flowcharts for data flow, sequence diagrams for interactions, and class diagrams for structural relationships.

### Directory layout

- `docs/global/baseline.md` — baseline manifest (curated required reads).
- `docs/global/general/{taxonomy}/` — on-demand cross-domain documentation.
- `docs/global/{domain}/{taxonomy}/` — domain-specific (e.g., `software-development`).
- `docs/project/{taxonomy}/` — project-scoped documentation.
- `docs/project/baseline.md` — project baseline manifest (curated required reads).

Global snippets are distributed to `~/.teleclaude/docs/` and available to all projects. Project snippets stay local to their repository.

## Allowed values

- `type`: principle, concept, policy, procedure, design, spec (canonical list in `teleclaude/constants.py:TAXONOMY_TYPES`).
- Third-party `type`: third-party.
- `scope`: global, domain, project.
- Third-party `scope`: global, project.
- `visibility`: public, internal. Default: `internal`.

## Known caveats

- Baseline manifests contain only `@` references and do not use frontmatter or H1 sections.
- Section headings must match the schema exactly; extra headings are invalid.
- For schema validation, "section headings" means the required H2 taxonomy sections. Subordinate headings inside a valid section are allowed.
- `docs/index.yaml` is auto-generated by `telec sync` — never hand-edit it.
