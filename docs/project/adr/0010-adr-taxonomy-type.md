---
id: 'project/adr/0010-adr-taxonomy-type'
type: 'adr'
domain: 'software-development'
scope: 'project'
visibility: 'public'
number: '10'
date: '2026-05-21'
adr_status: 'accepted'
description: 'ADRs become a first-class taxonomy type with their own required sections, frontmatter fields, and location at docs/project/adr/ (peer to spec, design, policy, procedure, concept).'
---

# ADR-0010: ADR Taxonomy Type — ADR

## Context

The existing `adr/` folder at the repo root contained one ADR — invisible to `telec docs index`, outside the schema-validated snippet system, and unreachable through the standard agent discovery mechanism. Agents reasoning about "why was this decided?" had no way to find ADRs via the normal `telec docs index --areas <type>` flow.

We wanted ADRs to be a first-class part of the doc-snippet system: discoverable, schema-validated, cross-referenceable. But they didn't fit any existing taxonomy:

- Not `principle` (a single decision, not a value).
- Not `policy` (a single decision, not a rule-set).
- Not `design` (a decided point, not shape exploration).
- Not `spec` (a historical record, not a contract).

We needed a new taxonomy type with its own required sections (Context / Decision / Consequences) and ADR-specific frontmatter (date, status, number, supersedes).

## Decision

Add `adr` as a new taxonomy type:

- `teleclaude/constants.py:TAXONOMY_TYPES` registers `adr`.
- `scripts/snippet_schema.yaml` defines required sections (Context, Decision, Consequences) and allowed (+ Alternatives Considered).
- `docs/global/general/spec/snippet-authoring-schema.md` documents the new type and its specific frontmatter fields: `date` (required), `adr_status` (required: proposed/accepted/deprecated/superseded), `number` (required, matches filename prefix), `supersedes` (optional list of ADR IDs).
- ADRs live at `docs/project/adr/NNNN-<kebab-case-title>.md` — top-level under `docs/project/`, peer to `spec/`, `design/`, `policy/`, `procedure/`, `concept/`. NOT under `design/`; ADRs are reasoning records, not design exploration.
- An ADR discipline policy (`general/policy/adr-discipline`) and an ADR authoring procedure (`general/procedure/adr-authoring`) cover when and how.
- The existing root `adr/` folder is removed; ADR-0001 is migrated to `docs/project/adr/0001-git-stash-prevention.md` with the new shape.

## Consequences

**Positive:**

- ADRs are discoverable via `telec docs index --areas adr`. Future agents asking "why was this decided?" can find them.
- Schema validation enforces the ADR shape (required sections, required frontmatter) — drift is caught at sync time.
- ADRs are cross-referenceable from any snippet via the standard `@` inline reference mechanism.
- The discipline (when to write an ADR) is codified as a policy, not buried as a sub-step of doc authoring.
- The existing ADR-0001 is preserved through migration; no historical decision-record is lost.

**Negative:**

- One more taxonomy type to maintain. New validators, new help-text, new examples. Modest ongoing cost.
- Schema docs and runtime schema (yaml) must be kept in sync by hand. A drift between them produces "the doc says X but the validator says Y" failure modes.
- Migrating ADR-0001 changed its location and frontmatter; any external reference to the old path breaks. Mitigation: the old path was outside the doc-snippet system and unlikely to be referenced anywhere durable.

## Alternatives Considered

- **Force-fit ADRs into `design` type.** Considered. Rejected: design's required sections (Purpose / Inputs-Outputs / Invariants / Primary flows / Failure modes) don't match the ADR shape. Forcing the fit produces awkward design docs and loses the semantic distinction between "we're exploring this" and "we decided this."
- **Leave ADRs in the root `adr/` folder, outside the doc-snippet system.** Considered. Rejected: invisible to `telec docs index`, no schema validation, no cross-referenceability. The discoverability gap was the original motivation for change.
- **Use the `design` type but in a `design/decisions/` subfolder.** Considered. Same fit problem as above plus a misleading folder name (the subfolder name doesn't change the type validation; sections still wouldn't match).
