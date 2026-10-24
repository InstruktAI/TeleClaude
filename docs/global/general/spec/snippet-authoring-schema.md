---
description: 'Schema and section requirements for documentation snippets belonging to a taxonomy.'
visibility: 'public'
---

# Snippet Authoring Schema — Spec

## What it is

Defines the required structure, section headings, and directory layout for documentation snippets.

## Canonical fields

Classification (`id`, `type`, `scope`, `domain`) is **derived from the file path** by the index build and materialized in the catalog of the half the snippet lives in — it is **never authored in frontmatter**. Validation separately enforces that the H1 type suffix matches the path-derived type. The index is the single source of truth for these four fields:

- `id` — unique snippet identifier, **derived** from the snippet's path below its
  half and, for a home's snippet, from the home's own declaration. There is one
  identity per snippet, the same from every location:
  - `<domain>/<taxonomy>/<rest>` — a domain snippet, published by the domain's
    owner from its `docs/global/<domain>/`. A project publishes only domain
    snippets.
  - `people/<slug>/<taxonomy>/<rest>` — a person's published snippet.
  - `companies/<slug>/<taxonomy>/<rest>` — a company's published snippet.
  - `local/projects/<slug>/<taxonomy>/<rest>`, `local/people/<slug>/<taxonomy>/<rest>`,
    `local/companies/<slug>/<taxonomy>/<rest>` — a snippet in the local half of a
    project, a person, or a company.

  An identity that begins with `local/` is indexed in place in its home and never
  published; every other identity is published. The two halves of a home
  therefore never share an identity. `<slug>` is the slug the home declares,
  never a directory name. Each catalog stores its entries under these qualified
  identities; no identity has a shorter or location-relative form.

- `type` — taxonomy type (see table below). **Derived** from the taxonomy directory path and checked against the H1 type-suffix by validation.
- `domain` — **Derived** as the first path segment of the id. It holds either a
  published knowledge domain (`general`, `sdlc`, and their peers) or a
  structural marker: `project`, `person`, or `company`. The last two
  are the home kinds whose identities begin with `people` and `companies`; a
  structural marker is never a published domain. A home's snippet is the
  exception to the first-segment rule: its identity begins with the plural home
  prefix (`people`, `companies`) or, in a local half, with `local` followed by
  the plural home prefix (`projects`, `people`, `companies`), and its derived
  domain is the home's kind — `project`, `person`, or `company` — never a prefix.
- `scope` — the tier the snippet belongs to: `global`, `project`, `person`, or
  `company`. **Derived** from the home and half: a domain snippet is `global`,
  a project's local snippet is `project`, and a person's or company's snippet
  carries that tier in both halves. More than one home of the same kind can be
  assembled into a single read at once, which is why every home's identity
  names the owner.

Frontmatter (required, authored):

- `description` — short summary of the snippet's purpose. This is the **only** required authored field.

Frontmatter (optional, authored):

- `visibility` — access classification: `public` or `internal`. Defaults to
  `internal` when omitted. It gates a caller who holds no declared relationship
  to the snippet's tier: such a caller sees only `public` snippets. A caller who
  holds a relationship to that tier reads it in full, and a platform admin reads
  every tier in full.

- `activation_trigger` — procedures only. A non-empty string describing when to activate the procedure. Appears in the "Activatable Procedures" section of its domain's generated bundle, or of the project's generated AGENTS.md for a project's own procedure, for progressive disclosure. Validation rejects this field on non-procedure snippet types.

- `subscriptions` — procedures only. A non-empty list of event type patterns whose arrival activates the procedure through the platform's procedure-activation contract. A pattern is an exact event type name, a prefix of whole name segments followed by `.*` (`erp.invoice.*` selects every event under `erp.invoice`), or `*`; any other form is rejected. An event type needs no registration in the platform event catalog to be subscribed to. A procedure declares `subscriptions` or `activation_trigger`, never both, because each names who is responsible for starting the work; a procedure used only as supporting knowledge declares neither. A procedure declaring `subscriptions` is excluded from the "Activatable Procedures" section and listed as a configured responsibility instead. Validation rejects this field on non-procedure snippet types, on a procedure published in a tier the procedure-activation contract does not route, and on a procedure declaring both activation fields.
- `subscription_home` — required on a procedure declaring `subscriptions`. The one kind of home the procedure works in: `company`, `person`, `project`, or `platform`. The procedure is activated only by events of a subscribed type whose origin is of that kind, and its agent works in the home that origin names; `platform` answers events whose origin is none and works in the platform's own checkout. A procedure published in a company's tier answers `company` and one published in a person's tier answers `person`; validation rejects any other kind there, a missing or unrecognized kind, and the field on any snippet that declares no `subscriptions`.

- `subscription_identity` — optional on a procedure declaring `subscriptions`. Which agent answers each activating event: `home`, the default when the field is omitted, is one agent for the procedure and the home, reached by every activating event of that home; `subject` is one agent for the procedure, the home and the event's subject, so each thing the events are about has its own agent, and a later event about the same thing reaches the agent that answered it before — woken when it is open, revived with its own context when it has closed. Validation rejects any other value, and the field on any snippet that declares no `subscriptions`.

- `subscription_attendance` — optional on a procedure declaring `subscriptions`. Whether people watch the procedure's agent: `attended`, the default when the field is omitted, is an agent shown wherever sessions are shown; `unattended` is an agent no person watches, left out of the places people look at sessions unless they ask for it, whose work is a run: once its session has closed it is never brought back, and a later event that would have reached it starts a new agent. Attendance changes nothing else about which agent answers an event, where it works, or what it may do. Validation rejects any other value, and the field on any snippet that declares no `subscriptions`.

- `role` — procedures only. The session role an agent carries when this procedure is its launch root: the procedure a dispatcher, a job declaration or a subscription names. The value names a role in the agent role catalog (`local/projects/teleclaude/spec/feature/identity/agent-roles`). Required on a procedure declaring `subscriptions` and on every procedure a dispatcher or job names. A procedure may be both a launch root and a dependency or hat another session reads: the entry declarations are interpreted only when the procedure is the launch root, and reading a procedure inside a session interprets none of them and changes nothing about that session. Validation rejects the field on any non-procedure snippet and a value the catalog does not name.
- `parameters` — procedures only, beside `role`. An ordered list of the arguments the procedure takes at its launch: each entry has `name`, optional `required` (bool, `false` when omitted: an entry is optional unless it says otherwise), and optional `default` (a literal string, meaningful only on an optional entry); at most one final entry may carry `rest: true`, taking the whole remaining argument text verbatim. Position is implicit from list order. The launch tokenizes the raw argument text on whitespace, binding one token per positional entry in order and the untokenized remainder to the `rest` entry; a required entry with no token refuses the launch before a session exists; an omitted optional entry takes its default or is absent; surplus tokens with no `rest` entry refuse the launch. A procedure declaring no `parameters` takes no arguments and refuses any. The loader that starts the session carries a preamble mapping each name to its bound value, and `$ARGUMENTS` names the raw argument text wherever a body refers to it. The entry context an entry type supplies — a job's name, an activation's home — is never a parameter. Validation rejects a duplicate name, a `rest` entry that is not last, a default on a required entry, and the field on a snippet that declares no `role`.
- `dispatch` — procedures only, beside `role`. The procedure's launch defaults: `agent`, a non-empty ordered agent preference list, and `thinking_mode`, one of `fast`, `med`, `slow`. A scheduled job's effective declaration overrides both for its own runs. Validation rejects an empty list, an unknown agent name, an unknown mode, and the field on a snippet that declares no `role`.

- `delivered_by` — list of todo slugs that materialize a **brand-new** snippet's intended state. Optional and non-empty when present; absence means the snippet describes the current platform contract. A snippet carrying `delivered_by` is **pending** and `telec docs index` flags it inline with a `(delivered by: <slugs>)` suffix (never hidden; the slug name is coordination metadata, not content). `telec docs index --target <slug>` narrows the listing to one todo's new snippets. The pending **body** stays invisible until active. Lifecycle code owns roadmap relationship checks and clears `delivered_by` on delivery (see `sdlc/principle/documentation-first-development` §10); source validation checks frontmatter shape and the index build records the source state it receives. `delivered_by` is the **only** pending-state frontmatter field. A change to an already-live snippet is **never** marked in frontmatter: its pending material lives in a companion filename (`<stem>.<slug>.md`), an in-body `&lt;!-- planned:slug --&gt;` block, or an in-body `&lt;!-- planned-change:slug --&gt;` block. The index derives the parallel `(superseded by: <slugs>)` suffix on the parent's line from companions, planned blocks, and planned-change blocks, not from any field.

- `date` — `adr` snippets ONLY (required). ISO-8601 date the decision was recorded.
- `number` — `adr` snippets ONLY (required). Integer matching the filename prefix (e.g., `0007` for `0007-provenance-via-mirror-id.md`).

Classification (`id`/`type`/`scope`/`domain`) is read from the file path by the index build, never authored in frontmatter. H1 type-suffix correctness is enforced by validation.

Third-party docs under `docs/third-party/` or `~/.teleclaude/docs/third-party/` are indexed separately from taxonomy snippets. They author only `description`; their `id` and `scope` are derived from their path below the third-party root, and they no longer carry `type`.

### Event delivery declarations

A procedure declaring `subscriptions` may also declare:

- `event_delivery`: `sequential` (default) or `batched`. This selects one oldest
  pending event or the ordered pending set at each eligible delivery boundary.
- `interruptible`: a boolean, default `false`. False admits activation events
  only at initial activation and wake entry; true also admits them at supported
  in-turn hook boundaries.

These fields are valid only on subscribed procedures. Their values are
independent: cardinality changes how many events are supplied, while
interruptibility changes when they may arrive. The runtime enforces the declared
delivery timing and cardinality.

Delivery settings configure a procedure session at initialization and remain
fixed for that session, including revival. Newly initialized successor sessions
use the current declaration. Publication changes do not reconfigure a running
agent beneath its assignment (`general/principle/trust-and-guardrails`).

A subscribed procedure explicitly declares its applicable shared event-handling
instructions in Required reads. A scheduled-job procedure likewise declares its
job-handling instructions. Publication and retrieval resolve those authored
references through the ordinary dependency graph; delivery metadata supplies
runtime settings rather than injecting documentation dependencies. Shared
handling duties are conditional on the actual invocation and its fixed settings,
including when the procedure is read inline
(`general/policy/referencing-doc-snippets`, `general/principle/priming`).

Document structure:

- H1 title with type suffix (e.g., `# Session Lifecycle — Design`).
- `## Required reads` — immediately after H1, with inline `@` references for hard dependencies. These are expanded (inlined) at build time.
- Required H2 sections per taxonomy (see table below).
- Additional structure inside valid sections is allowed. Use subordinate headings such as `###` when they improve clarity; schema validation constrains the required H2 section names, not the internal organization within them.
- `## Sources` — third-party docs may include web links or Context7 snippet IDs when authoritative references are available.
- `## See Also` — optional soft references (not inlined at build time).
- `<!-- @include: docs/snippets/<name>.md -->` — inlines a shared fragment's body exactly where the directive sits, in every rendering of the snippet: `telec docs get`, a session's assignment brief and generated bundles. It carries text several snippets state word for word, so it is written once. A fragment is authored under `docs/global/snippets/` and published as `docs/snippets/`; it has no frontmatter, is not a snippet and is never retrieved by ID. A fragment that cannot be found leaves its directive visible in the rendering.

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
behavioral anchor: it states the act the procedure's agent holds to at the
moment of acting, where the work is most likely to drift, as the reality
wanted from it (`general/policy/agent-facing-text`). An anchor another
procedure could carry equally is not a Discipline, and its measure is
specificity, never length.

`Known caveats` states the limits of a spec's current contract that a reader
would otherwise assume away: what the surface deliberately does not do or
support, what it does not recover from, and a capability built without a
consumer in what ships alongside it. Each caveat is current behavior, true
until a change to code or shipped configuration moves it. What a capability may
later be for is intent and lives in a todo; behavior a delivery will add is
pending material. How a designed system fails belongs in a design snippet's
`Failure modes`.

Supporting material stays subordinate to the required section that owns it:

- `### Examples` and `### Pre-completion checklist` belong inside `## Steps`.
- `### Report format` belongs inside `## Outputs`.

Examples demonstrate representative invocation patterns. They are
non-exhaustive and never define an allowlist; mandatory commands and prohibited
alternatives belong in the applicable numbered step or governing policy.

Design snippets should include Mermaid diagrams where visual representation aids understanding. Use flowcharts for data flow, sequence diagrams for interactions, and class diagrams for structural relationships.

### Directory layout

Every documentation home — a repository (the TeleClaude repository and every
registered project), a person's home, and a company's home — has the same two
halves:

- `docs/global/` — the **published** half. Publication copies it into
  `~/.teleclaude/docs/`, where it is served to every reader it admits.
- `docs/local/` — the **local** half. It is never published: it is indexed in
  place and served from the home's local index.

The half decides where a snippet is served from and whether its identity
carries the `local/` prefix. Outside a person's local half it never decides who
may read a snippet: reach and depth follow the reader's identity and the
snippet's `visibility` (`general/design/configuration-tiers`). A person's local
half is readable only by that person and the system principal
(`general/policy/artifact-scope`).

- `docs/global/{domain}/baseline.md` and `docs/global/{domain}/baseline-progressive.md` — a published domain's baseline manifests (curated required reads), generated into that domain's bundle; `general` is a domain like any other.
- `docs/global/{domain}/{taxonomy}/` — a published domain's documentation (e.g., `general`, `sdlc`).
- `docs/local/{taxonomy}/` — project-scoped documentation.

- `~/.teleclaude/people/{person}/docs/global/{taxonomy}/` and
  `~/.teleclaude/people/{person}/docs/local/{taxonomy}/` — a person's published
  and local documentation. Path-derived identity carries the tier and the
  person: `people/{person}/{taxonomy}/{rest}`.

- `~/.teleclaude/companies/{company}/docs/global/{taxonomy}/` and
  `~/.teleclaude/companies/{company}/docs/local/{taxonomy}/` — a company's
  published and local documentation.
- A repository's `docs/local/{taxonomy}/` snippets derive the identity
  `local/projects/{project}/{taxonomy}/{rest}`.
- A person's published half derives `people/{person}/{taxonomy}/{rest}` and their
  local half `local/people/{person}/{taxonomy}/{rest}`; a company's published half
  derives `companies/{company}/{taxonomy}/{rest}` and its local half
  `local/companies/{company}/{taxonomy}/{rest}`. Neither has a domain segment.
  Their published halves are deployed under `~/.teleclaude/docs/people/{person}/`
  and `~/.teleclaude/docs/companies/{company}/`.
- The same relative path under both halves of a home yields two snippets with two
  identities.
- `docs/local/spec/domain/{context}.md` — bounded-context domain spec (one per service).
- `{half}/spec/feature/{context}/{concept-name}.md` — feature spec (concept-named, hub in the hub-and-spoke model per `sdlc/principle/documentation-first-development`), under the half whose bounded context owns the behavior; `docs/local/` is the common one, not the only one. Contains Gherkin acceptance scenarios + business value. Many-to-many with todos via `delivered_by`.
- `docs/local/design/architecture/<topic>/overview.md` — canonical design snippet for a composite architecture topic. Named sibling design snippets carry independently useful facets; topic-owned non-Markdown companions may sit beside them.
- `<stem>.<slug>.md` (sibling to any `<stem>.md`) — a **companion**: the complete next version of `<stem>.md`, where `<slug>` is the delivering todo. A non-empty companion is a full snippet that shares the parent's derived `id` (the validator detects it by the sibling filename and exempts the id↔path / id-collision checks). An **empty** (zero-byte) companion is a **retirement**: the parent has no next version, the validator accepts it without snippet checks, and `telec docs get <id> --target <slug>` renders an empty pending view. The link lives entirely in the filename, the index never lists the companion, and default readers see the parent. On delivery a non-empty companion **replaces** the parent file and is deleted; an empty companion is deleted together with the parent. Bounded additions use in-body `&lt;!-- planned:slug --&gt;` blocks; bounded replacements and removals use in-body `&lt;!-- planned-change:slug --&gt;` blocks. All three live-parent carriers contribute to the parent's `(superseded by: <slugs>)` index suffix.
- `docs/local/adr/{NNNN}-{kebab-case-title}.md` — an `adr` snippet (type derived from the `adr/` path). Architectural decision records. Capture what was chosen and why, so specs/procedures/principles can describe the current state without becoming history logs. `date` and `number` are required additional frontmatter fields. ADRs sit at top-level under `docs/local/` (peer to `spec/`, `design/`, `policy/`, `procedure/`, `concept/`) — they are reasoning records, not design exploration, and do not belong under `design/`. An `adr` snippet carries no `delivered_by`, no `supersedes`, and no companion file — ADRs sit outside the pending/delivery machinery and do not cross-reference each other via frontmatter. The ADR body references earlier ADRs only (a backward in-prose reference); the one forward link is the optional `## Status` section's supersession pointer (`Superseded by ADR-NNNN` / `Superseded in part by ADR-NNNN` / `Deprecated`), added to an existing ADR when a later one supersedes it. `## Status` is the only part of an ADR that may change after authoring; the body is immutable.

- **In-body marker grammar.** The `planned`, `planned-change`, and `change` markers are **whole-line**: each occupies its own line, with only whitespace before its opening `<!--` and after its closing `-->`. Markers **never nest** — an in-body block holds only plain content between its own markers, never another `planned`/`planned-change` block, and two carriers never overlap. Marker validation rejects inline (mid-prose) and nested markers as malformed, so every accepted marker is one the delivery fold can resolve.

- `docs/local/baseline.md` — project baseline manifest (curated required reads).

Published snippets are distributed to `~/.teleclaude/docs/` under their identity. Local snippets stay in their home and are served from its local index; a reader reaches them from any location by naming the home's local half or a snippet's `local/` identity, at the depth the reader holds, and a person's local half admits only that person and the system principal.

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
- `scope`: global, project, person, company.
- Home identity prefixes: `projects`, `people`, `companies`, and the local-half
  prefix `local`. They are reserved: no published domain carries one of these
  names.

- `visibility`: public, internal. Default: `internal`.

## Known caveats

- Baseline manifests contain only `@` references and do not use frontmatter or H1 sections.
- Section headings must match the schema exactly; extra headings are invalid.
- For schema validation, "section headings" means the required H2 taxonomy sections. Subordinate headings inside a valid section are allowed.

- The catalogs of both halves (`docs/global/index.yaml`, `docs/local/index.yaml`) are generated by the index build — never hand-edit them.
