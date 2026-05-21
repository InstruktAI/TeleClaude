---
id: 'general/policy/adr-discipline'
type: 'policy'
domain: 'general'
scope: 'global'
visibility: 'public'
description: 'When agents commit a non-trivial decision into documentation, the reasoning must land in an ADR — not in the spec, procedure, or principle itself. Keeps primary artifacts clean and current; gives future agents a discoverable, auditable record of why things are the way they are.'
---

# ADR Discipline — Policy

## Required reads

- @~/.teleclaude/docs/general/spec/snippet-authoring-schema.md
- @~/.teleclaude/docs/general/procedure/adr-authoring.md

## Rules

- When authoring or modifying a doc snippet, agent artifact, or architecture document, an Architectural Decision Record (ADR) MUST accompany the change if the change embeds a non-trivial decision.
- A "non-trivial decision" is one a future agent might reasonably question or want to understand the rationale for. The discriminator: if reading the resulting snippet would prompt "why was it done this way?" — an ADR is required.
- The ADR is authored BEFORE or ALONGSIDE the primary artifact change, never retroactively long after.
- ADRs live at `docs/project/adr/NNNN-<kebab-case-title>.md` (peer to `spec/`, `design/`, `policy/`, `procedure/`, `concept/` — NOT under `design/`, because ADRs are reasoning records, not design exploration), follow the `type: adr` schema (Context / Decision / Consequences, with required `date`, `adr_status`, and `number` frontmatter), and are discovered via `telec docs index --areas adr`.
- Primary artifacts (specs, procedures, principles) MUST describe the *current state* — they are NOT reasoning logs. The reasoning belongs in the accompanying ADR, not inline.
- When an ADR supersedes a prior decision, the new ADR's `supersedes` frontmatter cites the prior ADR's id, and the prior ADR's `adr_status` is updated to `superseded`.

## Rationale

Without this discipline, the reasoning trail ends up inline in primary artifacts, which produces three failure modes: (1) specs/procedures rot into history logs that conflate "what is" with "what was considered," making them harder to consume; (2) the same decision is re-derived repeatedly because the rationale is buried in old commit messages or chat transcripts no agent will ever read; (3) when a decision is reversed, the inline reasoning becomes contradictory and confusing rather than cleanly superseded. ADRs separate the two concerns: primary artifacts describe the actual contract; ADRs preserve the why. Both stay clean and current.

## Scope

All agents authoring or modifying:

- Doc snippets under `docs/`
- Agent artifacts under `agents/` or `.agents/`
- Architecture documents under `docs/project/design/architecture/` or `docs/project/design/architecture-v2/`
- Policies, principles, procedures, concepts, specs at any level

## Enforcement

- The doc-snippet-authoring procedure cross-references this policy: agents authoring snippets must consult ADR discipline as part of the procedure.
- The agent-artifact-authoring procedure cross-references this policy: agents authoring artifacts must do the same.
- Reviewers verify an ADR accompanies any non-trivial doc change.
- A future lifecycle check at commit time MAY enforce this automatically by detecting decision-embedded changes without a paired ADR; not yet implemented.

## Exceptions

- **Trivial changes.** Typos, formatting, example additions, reorganization without semantic change, broken-reference fixes. No ADR required.
- **Inventory documentation.** When documenting existing state that wasn't the result of a fresh decision (e.g., the v1-inventory feature snippets describing already-implemented behavior), no ADR is required for the inventory work itself. The decision was made when the original implementation landed; the inventory is just describing reality.
- **Internal-only changes inside a snippet's body** that don't reflect a decision — clarifying wording, restructuring a section for readability. No ADR.

If unsure whether an ADR is required, default to writing one. Cost of an extra ADR is low; cost of a missed decision-record compounds.
