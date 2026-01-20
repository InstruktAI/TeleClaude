---
description: How to author TeleClaude snippets and choose taxonomy-appropriate structure.
id: teleclaude/snippets/authoring
requires:
- ai-collaboration/principles/priming
scope: project
type: guide
---

Purpose

- Make snippets the authoritative, reusable source for AI context selection.
- Capture intent, boundaries, and guarantees without drifting from code and docs.
- Keep snippets atomic: they are small context units a selector can combine to prime an AI.
- Snippets may point to background material for depth or provenance.

Principles

- **Priming focus**: see ai-collaboration/principles/priming.
- **Truth over completeness**: reflect the real system, not idealized intent.
- **Explain the why**: capture guarantees, invariants, and boundaries that guide usage.
- **Concrete over generic**: use real component names/events where it clarifies behavior.
- **Standalone**: make each snippet clear on its own; `requires` only add depth.
- **Reusability**: split only when the parts are independently useful.

Taxonomy

- **policy**: rules, constraints, non-negotiables.
- **standard**: enforced conventions or quality bars.
- **guide**: recommended approach or best practice.
- **procedure**: ordered steps with outputs.
- **principles**: high-level governing ideas that shape design and judgment.
- **role**: identity, responsibilities, boundaries.
- **checklist**: verification or readiness criteria.
- **reference**: static facts or lookup tables.
- **concept**: definitions or framing.
- **architecture**: system structure, components, and relationships.
- **decision**: rationale for a chosen approach.
- **example**: concrete usage or implementation/pattern.
- **incident**: postmortems and lessons learned.
- **timeline**: time-ordered events.
- **faq**: recurring questions and answers.

Frontmatter

- `id`: stable path-like identifier for selection.
- `type`: one taxonomy value.
- `scope`: `global`, `domain`, or `project`.
- `description`: concise semantic summary.
- `requires`: optional list of supporting snippets or docs.

Frontmatter heuristics

- **ID**: write a path-shaped identifier following `domain/area/topic` (e.g. `teleclaude/architecture/daemon-lifecycle`).
- **Type**: pick the taxonomy that matches the snippet’s purpose.
- **Scope**: choose the true applicability (`project`, `domain`, `global`).
- **Requires**: list snippet IDs (from `docs/index.yaml`) that are mandatory reading to interpret this snippet correctly.
- **Description**: a concise semantic summary of the snippet’s content.

Description heuristics

- **Match the content**: summarize what the snippet actually says.
- **Disambiguate**: if a term has multiple meanings, specify which one this is.
- **Non-procedural**: don’t describe steps; summarize the concept.
- **Concise**: one sentence, focused on meaning.

Frontmatter examples

Minimal (no dependencies)

```yaml
---
id: teleclaude/architecture/daemon-lifecycle
type: architecture
scope: project
description: Core lifecycle of the TeleClaude daemon and its major responsibilities.
---
```

With dependencies

```yaml
---
id: teleclaude/architecture/system-overview
type: architecture
scope: project
description: High-level component map of TeleClaude daemon, adapters, transport, and storage.
requires:
  - teleclaude/concept/adapter-types
  - teleclaude/concept/resource-models
---
```

Requires usage

- Use `requires` for **mandatory reading**: the snippet should not be interpreted without it.
- Do not read snippet content; select dependencies by semantics from `docs/index.yaml`.
- Required-reading heuristics:
  - **Dependency of meaning**: misinterpretation is likely without another snippet’s definitions.
  - **Non-obvious constraints**: another snippet supplies a rule that governs this one.
  - **Boundary assumptions**: another snippet defines the boundary or interface this snippet assumes.
  - **Concept reuse**: another snippet is the canonical concept this one builds on.
  - **Risk of wrong action**: missing context would cause incorrect implementation or ops behavior.
  - **Intent inheritance**: the “why” is defined elsewhere and must shape interpretation.
  - **Layered reading**: this snippet is a leaf that relies on a parent explanation.

Schemas by taxonomy

Principles

- Principle statement
- Rationale
- Implications for design and decision-making
- Tensions or tradeoffs

Architecture / Concept

- Purpose
- Boundaries or inputs/outputs
- Invariants
- Primary flows
- Failure modes
- If structure or integrations are central, include a small Mermaid diagram.

Policy / Standard

- Rule
- Rationale
- Scope
- Enforcement or checks
- Exceptions or edge cases

Procedure / Checklist / Guide

- Goal
- Preconditions
- Steps or checks
- Outputs or verification
- Recovery or stop conditions

Reference / Example

- What it is
- Canonical fields or shape
- Allowed values
- Known caveats

FAQ

- Use for recurring questions that would otherwise be answered repeatedly.
- Include: question, answer.
- Exclude: one-off clarifications or internal notes.

References

- `requires` should list snippet IDs; inline `@...` references should be root-relative (e.g., `@docs/snippets/...`).
- References prime context; the snippet body still needs to explain the concept on its own.
