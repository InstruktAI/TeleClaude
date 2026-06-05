---
description: 'Schema and section requirements for documentation snippets belonging to a taxonomy.'
id: 'general/spec/snippet-authoring-schema'
scope: 'global'
type: 'spec'
visibility: 'public'
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
- `status` — **deprecated.** Legacy lifecycle field accepted by the parser for backward compatibility but no longer part of the discipline. New snippets must not set it; use `delivered_by:` presence/absence to signal pending vs. current state.
- `delivered_by` — list of todo slugs that will materialize this snippet's intended state. Optional and non-empty when present; absence means the snippet describes the current platform contract. Lifecycle code owns roadmap relationship checks and clears `delivered_by` when the relevant delivery state changes; `telec sync` validates frontmatter shape and indexes the source state it receives.
- `diff_of` — `spec-diff` snippets ONLY (required for that type, forbidden on every other type). Snippet id of the parent spec this diff modifies. Validated to point at an existing snippet of `type: spec`. The diff is read alongside the parent; together they describe v2 behavior for the concept.
- `date` — `adr` snippets ONLY (required). ISO-8601 date the decision was recorded.
- `adr_status` — `adr` snippets ONLY (required). One of `proposed`, `accepted`, `deprecated`, `superseded`. Captures the decision's standing.
- `number` — `adr` snippets ONLY (required). Integer matching the filename prefix (e.g., `0007` for `0007-provenance-via-mirror-id.md`).
- `supersedes` — `adr` snippets ONLY (optional). List of ADR IDs this decision replaces.

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
| spec-diff | Replaces, Adds, Removes, Why                                           |
| adr       | Context, Decision, Consequences (optional: Alternatives Considered)    |

Procedure sections may also include optional: `Pre-completion checklist`, `Report format`, `Required tools`, `Discipline`.

The `Discipline` section is the behavioral anchor — 3–5 sentences naming the specific failure mode this procedure guards against. Commands are thin wrappers that delegate to their procedure's discipline (`Follow the <procedure>'s discipline.`); the section must live on the procedure so the delegation resolves.

The `Required tools` section lists `telec` commands the agent must use during this procedure. Commands listed here are mandatory — agents must not improvise alternatives (direct file reads, custom scripts). Each entry is a concrete command pattern. Globally expanded commands (available to all agents via the CLI surface) are listed by their top-level signature. Procedure-scoped commands are listed with full invocation patterns.

Design snippets should include Mermaid diagrams where visual representation aids understanding. Use flowcharts for data flow, sequence diagrams for interactions, and class diagrams for structural relationships.

### Directory layout

- `docs/global/baseline.md` — baseline manifest (curated required reads).
- `docs/global/general/{taxonomy}/` — on-demand cross-domain documentation.
- `docs/global/{domain}/{taxonomy}/` — domain-specific (e.g., `software-development`).
- `docs/project/{taxonomy}/` — project-scoped documentation.
- `docs/project/spec/domain/{context}.md` — bounded-context domain spec (one per service).
- `docs/project/spec/feature/{context}/{concept-name}.md` — feature spec (concept-named, hub in the hub-and-spoke model per `software-development/principle/documentation-first-development`). Contains Gherkin acceptance scenarios + business value. Many-to-many with todos via `delivered_by`.
- `docs/project/spec/**/{stem}-v2-diff.md` — `type: spec-diff` companion living as a sibling to its parent spec (`{stem}.md`). Captures how a declared successor implementation track diverges from the parent. TeleClaude names that successor track `v2`; other projects must declare their own migration vocabulary before using this convention. Migration-window-only: deleted (merged into the parent) when the relevant cutover delivers. See `software-development/principle/documentation-first-development` section 10 for the spec-diff companion infrastructure.
- `docs/project/adr/{NNNN}-{kebab-case-title}.md` — `type: adr`. Architectural decision records. Capture what was chosen and why, so specs/procedures/principles can describe the current state without becoming history logs. `date`, `adr_status`, and `number` are required additional frontmatter fields. Optional: `supersedes` (list of ADR IDs this one replaces). ADRs sit at top-level under `docs/project/` (peer to `spec/`, `design/`, `policy/`, `procedure/`, `concept/`) — they are reasoning records, not design exploration, and do not belong under `design/`.
- `docs/project/baseline.md` — project baseline manifest (curated required reads).

Global snippets are distributed to `~/.teleclaude/docs/` and available to all projects. Project snippets stay local to their repository.

### Grouped snippets — folder convention

When multiple snippets share a topic (e.g., a general procedure plus thin-wrapper variants, or a design family with several facets), they live together in a folder named for the topic. The folder contains:

- `overview.md` — the top-level or shared snippet for the group (e.g., the general procedure that variants build on).
- Sibling files for specialized variants or facets, named for what they cover (e.g., `human.md`, `project.md`, `prepare.md`, `work.md`).

The folder name becomes part of every member snippet's id (e.g., `general/procedure/memory-extraction/overview`, `general/procedure/memory-extraction/human`). Variants reference the overview as a required read. All members share the same taxonomy type — a folder under `procedure/` contains only `procedure` snippets.

Apply this convention whenever a group of related snippets would otherwise produce a flat sibling list with shared-prefix filenames (e.g., `foo-overview.md`, `foo-human.md`, `foo-project.md` becomes `foo/overview.md`, `foo/human.md`, `foo/project.md`). The flat-prefix anti-pattern is rejected at review.

## Allowed values

- `type`: principle, concept, policy, procedure, design, spec, spec-diff, adr (canonical list in `teleclaude/constants.py:TAXONOMY_TYPES`).
- Third-party `type`: third-party.
- `scope`: global, domain, project.
- Third-party `scope`: global, project.
- `visibility`: public, internal. Default: `internal`.

## Known caveats

- Baseline manifests contain only `@` references and do not use frontmatter or H1 sections.
- Section headings must match the schema exactly; extra headings are invalid.
- For schema validation, "section headings" means the required H2 taxonomy sections. Subordinate headings inside a valid section are allowed.
- `docs/index.yaml` is auto-generated by `telec sync` — never hand-edit it.
