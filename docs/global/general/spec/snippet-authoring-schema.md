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
<!-- planned-change:docs-tier-layering -->
- `scope` — `global` or `project`. **Derived** from the path (`docs/global/**` → `global`, `docs/project/**` → `project`).
<!-- change:docs-tier-layering -->
- `scope` — the tier the snippet belongs to: `global`, `project`, `person`, or
  `company`. **Derived** from the path. Snippets under a person's or a company's
  documentation tree carry that tier and an identity that names which person or
  which company, because more than one tier of the same kind can be assembled
  into a single index at once and an unqualified identity would be ambiguous
  between them.
<!-- /planned-change:docs-tier-layering -->

Frontmatter (required, authored):

- `description` — short summary of the snippet's purpose. This is the **only** required authored field.

Frontmatter (optional, authored):

<!-- planned-change:docs-tier-layering -->
- `visibility` — access classification: `public` or `internal`. Defaults to `internal` when omitted. Admin callers see all snippets; non-admin callers see only `public` snippets.
<!-- change:docs-tier-layering -->
- `visibility` — access classification: `public` or `internal`. Defaults to
  `internal` when omitted. It gates a caller who holds no declared relationship
  to the snippet's tier: such a caller sees only `public` snippets. A caller who
  holds a relationship to that tier reads it in full, and a platform admin reads
  every tier in full.
<!-- /planned-change:docs-tier-layering -->
- `activation_trigger` — procedures only. A non-empty string describing when to activate the procedure. Appears in the "Activatable Procedures" section of generated AGENTS.md for progressive disclosure. Validation rejects this field on non-procedure snippet types.

- `delivered_by` — list of todo slugs that materialize a **brand-new** snippet's intended state. Optional and non-empty when present; absence means the snippet describes the current platform contract. A snippet carrying `delivered_by` is **pending** and `telec docs index` flags it inline with a `(delivered by: <slugs>)` suffix (never hidden; the slug name is coordination metadata, not content). `telec docs index --target <slug>` narrows the listing to one todo's new snippets. The pending **body** stays invisible until active. Lifecycle code owns roadmap relationship checks and clears `delivered_by` on delivery (see `software-development/principle/documentation-first-development` §10); `telec sync` validates frontmatter shape and indexes the source state it receives. `delivered_by` is the **only** pending-state frontmatter field. A change to an already-live snippet is **never** marked in frontmatter: its pending material lives in a companion filename (`<stem>.<slug>.md`), an in-body `&lt;!-- planned:slug --&gt;` block, or an in-body `&lt;!-- planned-change:slug --&gt;` block. The index derives the parallel `(superseded by: <slugs>)` suffix on the parent's line from companions, planned blocks, and planned-change blocks, not from any field.

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

| Taxonomy  | Required sections                                                           |
| --------- | --------------------------------------------------------------------------- |
| principle | Principle, Rationale, Implications, Tensions                                |
| concept   | What, Why                                                                   |
| policy    | Rules, Rationale, Scope, Enforcement, Exceptions                            |
| procedure | Goal, Preconditions, Steps, Outputs, Recovery                               |
| design    | Purpose, Inputs/Outputs, Invariants, Primary flows, Failure modes           |
| spec      | What it is, Canonical fields (optional: Allowed values, Known caveats)      |
| adr       | Context, Decision, Consequences (optional: Alternatives Considered, Status) |

`Discipline` is the only additional procedure H2. It is optional unless an
agent command explicitly delegates to that procedure's discipline; such a
delegation requires the procedure to define it. The section is the procedure's
behavioral anchor: 3–5 sentences naming the specific failure mode the procedure
guards against.

Supporting material stays subordinate to the required section that owns it:

- `### Examples` and `### Pre-completion checklist` belong inside `## Steps`.
- `### Report format` belongs inside `## Outputs`.

Examples demonstrate representative invocation patterns. They are
non-exhaustive and never define an allowlist; mandatory commands and prohibited
alternatives belong in the applicable numbered step or governing policy.

Design snippets should include Mermaid diagrams where visual representation aids understanding. Use flowcharts for data flow, sequence diagrams for interactions, and class diagrams for structural relationships.

### Directory layout

- `docs/global/baseline.md` — baseline manifest (curated required reads).
- `docs/global/general/{taxonomy}/` — on-demand cross-domain documentation.
- `docs/global/{domain}/{taxonomy}/` — domain-specific (e.g., `software-development`).
- `docs/project/{taxonomy}/` — project-scoped documentation.
- `docs/project/spec/domain/{context}.md` — bounded-context domain spec (one per service).
- `docs/project/spec/feature/{context}/{concept-name}.md` — feature spec (concept-named, hub in the hub-and-spoke model per `software-development/principle/documentation-first-development`). Contains Gherkin acceptance scenarios + business value. Many-to-many with todos via `delivered_by`.
- `docs/project/design/architecture/<topic>/overview.md` — canonical design snippet for a composite architecture topic. Named sibling design snippets carry independently useful facets; topic-owned non-Markdown companions may sit beside them.
- `<stem>.<slug>.md` (sibling to any `<stem>.md`) — a **companion**: the complete next version of `<stem>.md`, where `<slug>` is the delivering todo. A full snippet that shares the parent's derived `id` (the validator detects it by the sibling filename and exempts the id↔path / id-collision checks). The link lives entirely in the filename, the index never lists the companion, and default readers see the parent. On delivery the companion **replaces** the parent file and is deleted. Bounded additions use in-body `&lt;!-- planned:slug --&gt;` blocks; bounded replacements and removals use in-body `&lt;!-- planned-change:slug --&gt;` blocks. All three live-parent carriers contribute to the parent's `(superseded by: <slugs>)` index suffix.
- `docs/project/adr/{NNNN}-{kebab-case-title}.md` — an `adr` snippet (type derived from the `adr/` path). Architectural decision records. Capture what was chosen and why, so specs/procedures/principles can describe the current state without becoming history logs. `date` and `number` are required additional frontmatter fields. ADRs sit at top-level under `docs/project/` (peer to `spec/`, `design/`, `policy/`, `procedure/`, `concept/`) — they are reasoning records, not design exploration, and do not belong under `design/`. An `adr` snippet carries no `delivered_by`, no `supersedes`, and no companion file — ADRs sit outside the pending/delivery machinery and do not cross-reference each other via frontmatter. The ADR body references earlier ADRs only (a backward in-prose reference); the one forward link is the optional `## Status` section's supersession pointer (`Superseded by ADR-NNNN` / `Superseded in part by ADR-NNNN` / `Deprecated`), added to an existing ADR when a later one supersedes it. `## Status` is the only part of an ADR that may change after authoring; the body is immutable.

- **In-body marker grammar.** The `planned`, `planned-change`, and `change` markers are **whole-line**: each occupies its own line, with only whitespace before its opening `<!--` and after its closing `-->`. Markers **never nest** — an in-body block holds only plain content between its own markers, never another `planned`/`planned-change` block, and two carriers never overlap. `telec sync` rejects inline (mid-prose) and nested markers as malformed, so every accepted marker is one the delivery fold can resolve.

- `docs/project/baseline.md` — project baseline manifest (curated required reads).

Global snippets are distributed to `~/.teleclaude/docs/` and available to all projects. Project snippets stay local to their repository.

### Grouped snippets — folder convention

When multiple snippets share a topic (e.g., a general procedure plus thin-wrapper variants, or a design family with several facets), they live together in a folder named for the topic. The folder contains:

- `overview.md` — the top-level or shared snippet for the group (e.g., the general procedure that variants build on).
- Sibling files for specialized variants or facets, named for what they cover (e.g., `human.md`, `project.md`, `prepare.md`, `work.md`).

The folder name becomes part of every member snippet's id (e.g., `general/procedure/memory-extraction/overview`, `general/procedure/memory-extraction/human`). Variants reference the overview as a required read. All members share the same taxonomy type — a folder under `procedure/` contains only `procedure` snippets.

Apply this convention whenever a group of related snippets would otherwise produce a flat sibling list with shared-prefix filenames (e.g., `foo-overview.md`, `foo-human.md`, `foo-project.md` becomes `foo/overview.md`, `foo/human.md`, `foo/project.md`). The flat-prefix anti-pattern is rejected at review.

Non-Markdown source and rendered assets owned exclusively by a grouped topic
may live beside its snippets. They are companions, not snippet members: they do
not receive taxonomy metadata, cannot replace the group's `overview.md`, and do
not relax the rule that all Markdown members share one taxonomy type. A
composite architecture topic may therefore contain `overview.md`, named design
facets, `canvas.excalidraw`, and an optional consumed `canvas.svg`. Keep an SVG
only when documentation or another durable surface uses it; generated renders
do not accumulate by default.

## Allowed values

- `type`: principle, concept, policy, procedure, design, spec, adr (canonical list in `teleclaude/constants.py:TAXONOMY_TYPES`).
<!-- planned-change:docs-tier-layering -->
- `scope`: global, project.
<!-- change:docs-tier-layering -->
- `scope`: global, project, person, company.
<!-- /planned-change:docs-tier-layering -->
- `visibility`: public, internal. Default: `internal`.

## Known caveats

- Baseline manifests contain only `@` references and do not use frontmatter or H1 sections.
- Section headings must match the schema exactly; extra headings are invalid.
- For schema validation, "section headings" means the required H2 taxonomy sections. Subordinate headings inside a valid section are allowed.

- `docs/index.yaml` is auto-generated by `telec sync` — never hand-edit it.
