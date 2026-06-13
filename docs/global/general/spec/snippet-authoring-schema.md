---
description: 'Schema and section requirements for documentation snippets belonging to a taxonomy.'
visibility: 'public'
---

# Snippet Authoring Schema — Spec

## What it is

Defines the required structure, section headings, and directory layout for documentation snippets.

## Canonical fields

Classification (`id`, `type`, `scope`, `domain`) is **derived from the file path** by the index build (`docs/index.yaml`) and materialized there — it is **never authored in frontmatter**. Validation separately enforces that the H1 type suffix matches the path-derived type. The index is the single source of truth for these four fields:

- `id` — unique snippet identifier. **Derived** from the snippet's path below the docs root.
- `type` — taxonomy type (see table below). **Derived** from the taxonomy directory path and checked against the H1 type-suffix by validation.
- `domain` — knowledge domain (`general`, `<domain>` such as `software-development`, or `project`). **Derived** as the first path segment of the id.
- `scope` — `global` or `project`. **Derived** from the path (`docs/global/**` → `global`, `docs/project/**` → `project`).

Frontmatter (required, authored):

- `description` — short summary of the snippet's purpose. This is the **only** required authored field.

Frontmatter (optional, authored):

- `visibility` — access classification: `public` or `internal`. Defaults to `internal` when omitted. Admin callers see all snippets; non-admin callers see only `public` snippets.
- `activation_trigger` — procedures only. A non-empty string describing when to activate the procedure. Appears in the "Activatable Procedures" section of generated AGENTS.md for progressive disclosure. Validation rejects this field on non-procedure snippet types.
<!-- planned-change:planned-change-markers -->
- `delivered_by` — list of todo slugs that will materialize this **brand-new** snippet's intended state. Optional and non-empty when present; absence means the snippet describes the current platform contract. A snippet carrying `delivered_by` is **pending** — not yet a live contract — so `telec docs index` flags it inline with a `(delivered by: <slugs>)` suffix (never hidden; the slug name is coordination metadata, not content), and `telec docs index --target <slug>` narrows the listing to one todo's new snippets. The pending **body** stays invisible until active. Lifecycle code owns roadmap relationship checks and clears `delivered_by` on delivery (see `software-development/principle/documentation-first-development` §10); `telec sync` validates frontmatter shape and indexes the source state it receives. `delivered_by` is the **only** pending-state frontmatter field. A change to an already-live snippet is **never** marked in frontmatter — its pending material lives in the companion filename (`<stem>.<slug>.md`) or an in-body `<!-- planned:slug -->` block, and the index derives the parallel `(superseded by: <slugs>)` suffix on the parent's line from those, not from any field.
<!-- change:planned-change-markers -->
- `delivered_by` — list of todo slugs that materialize a **brand-new** snippet's intended state. Optional and non-empty when present; absence means the snippet describes the current platform contract. A snippet carrying `delivered_by` is **pending** and `telec docs index` flags it inline with a `(delivered by: <slugs>)` suffix (never hidden; the slug name is coordination metadata, not content). `telec docs index --target <slug>` narrows the listing to one todo's new snippets. The pending **body** stays invisible until active. Lifecycle code owns roadmap relationship checks and clears `delivered_by` on delivery (see `software-development/principle/documentation-first-development` §10); `telec sync` validates frontmatter shape and indexes the source state it receives. `delivered_by` is the **only** pending-state frontmatter field. A change to an already-live snippet is **never** marked in frontmatter: its pending material lives in a companion filename (`<stem>.<slug>.md`), an in-body `<!-- planned:slug -->` block, or an in-body `<!-- planned-change:slug -->` block. The index derives the parallel `(superseded by: <slugs>)` suffix on the parent's line from companions, planned blocks, and planned-change blocks, not from any field.
<!-- /planned-change:planned-change-markers -->
- `date` — `adr` snippets ONLY (required). ISO-8601 date the decision was recorded.
- `number` — `adr` snippets ONLY (required). Integer matching the filename prefix (e.g., `0007` for `0007-provenance-via-mirror-id.md`).

Classification (`id`/`type`/`scope`/`domain`) is read from the file path by the index build, never authored in frontmatter. H1 type-suffix correctness is enforced by validation.

Third-party docs under `docs/third-party/` or `~/.teleclaude/docs/third-party/` are indexed separately from taxonomy snippets. They author only `description`; their `id` and `scope` are derived from their path below the third-party root, and they no longer carry `type`.

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
<!-- planned-change:planned-change-markers -->
- `<stem>.<slug>.md` (sibling to any `<stem>.md`) — a **companion**: the complete next version of `<stem>.md`, where `<slug>` is the delivering todo. A full snippet that shares the parent's derived `id` (the validator detects it by the sibling filename and exempts the id↔path / id-collision checks). The link lives entirely in the filename — the parent carries **no** pending marker, and the index never lists the companion. Pending-only and invisible to default readers: on delivery the companion **replaces** the parent file and is deleted. A v1→v2 migration is just another slug. See `software-development/principle/documentation-first-development` §10.
<!-- change:planned-change-markers -->
- `<stem>.<slug>.md` (sibling to any `<stem>.md`) — a **companion**: the complete next version of `<stem>.md`, where `<slug>` is the delivering todo. A full snippet that shares the parent's derived `id` (the validator detects it by the sibling filename and exempts the id↔path / id-collision checks). The link lives entirely in the filename, the index never lists the companion, and default readers see the parent. On delivery the companion **replaces** the parent file and is deleted. Bounded additions use in-body `<!-- planned:slug -->` blocks; bounded replacements and removals use in-body `<!-- planned-change:slug -->` blocks. All three live-parent carriers contribute to the parent's `(superseded by: <slugs>)` index suffix.
<!-- /planned-change:planned-change-markers -->
- `docs/project/adr/{NNNN}-{kebab-case-title}.md` — an `adr` snippet (type derived from the `adr/` path). Architectural decision records. Capture what was chosen and why, so specs/procedures/principles can describe the current state without becoming history logs. `date` and `number` are required additional frontmatter fields. ADRs sit at top-level under `docs/project/` (peer to `spec/`, `design/`, `policy/`, `procedure/`, `concept/`) — they are reasoning records, not design exploration, and do not belong under `design/`. An `adr` snippet carries no `delivered_by`, no `supersedes`, and no companion file — ADRs sit outside the pending/delivery machinery and do not cross-reference each other via frontmatter; a backward in-prose reference to an earlier ADR is the only inter-ADR link.
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
- `scope`: global, project.
- `visibility`: public, internal. Default: `internal`.

## Known caveats

- Baseline manifests contain only `@` references and do not use frontmatter or H1 sections.
- Section headings must match the schema exactly; extra headings are invalid.
- For schema validation, "section headings" means the required H2 taxonomy sections. Subordinate headings inside a valid section are allowed.
- `docs/index.yaml` is auto-generated by `telec sync` — never hand-edit it.
