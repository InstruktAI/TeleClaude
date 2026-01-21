---
description: How to author TeleClaude snippets and choose taxonomy-appropriate structure.
id: teleclaude/snippets/authoring
requires:
  - ai-collaboration/principles/priming
scope: project
type: guide
---

## Goal

- Author snippets that are accurate, reusable, and aligned with the taxonomy and selection pipeline.

## Preconditions

- The relevant code and legacy docs have been reviewed.
- The snippet index is available at `docs/snippets/index.yaml`.

## Steps

1. Apply the priming and truthfulness principles from `ai-collaboration/principles/priming`.
2. Choose the taxonomy type that matches the snippet’s purpose.
3. Write frontmatter using the required schema (`id`, `type`, `scope`, `description`, `requires`).
4. Use the taxonomy schema below to structure the body with `##` headings.
5. Add required-reading dependencies using snippet IDs from `docs/snippets/index.yaml`.
6. Include a mermaid diagram when structure or integration is central to understanding.

## Outputs

- A snippet that is atomic, structured, and aligned with the current system.

## Recovery

- If the snippet conflicts with code or legacy docs, reconcile the source and update the snippet.

## Frontmatter heuristics

- **ID**: path-shaped identifier like `domain/area/topic` (e.g., `teleclaude/architecture/daemon-lifecycle`).
- **Type**: single taxonomy value that matches the snippet’s purpose.
- **Scope**: true applicability (`project`, `domain`, `global`).
- **Requires**: list snippet IDs that are mandatory reading for correct interpretation.
- **Description**: concise semantic summary of the snippet’s content.

## Description heuristics

- Match the content; avoid procedural wording.
- Disambiguate overloaded terms.
- One sentence, focused on meaning.

## Frontmatter examples

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

## Required-reading heuristics

- Dependency of meaning: definitions elsewhere are required to interpret this snippet.
- Non-obvious constraints: a governing rule is defined in another snippet.
- Boundary assumptions: this snippet relies on a boundary described elsewhere.
- Concept reuse: a canonical concept snippet should be read first.
- Risk of wrong action: missing context would cause incorrect implementation or ops behavior.
- Intent inheritance: the “why” is defined elsewhere and must shape interpretation.
- Layered reading: this snippet is a leaf that relies on a parent explanation.

## Schemas by taxonomy

Use `##` headings for each section.

Principles

## Principle

- Principle statement

## Rationale

- Rationale

## Implications

- Implications for design and decision-making

## Tensions

- Tensions or tradeoffs

Architecture / Concept

## Purpose

- Purpose

## Inputs/Outputs

- Boundaries or inputs/outputs

## Invariants

- Invariants

## Primary flows

- Primary flows

## Failure modes

- Failure modes

Policy / Standard

## Rule

- Rule

## Rationale

- Rationale

## Scope

- Scope

## Enforcement or checks

- Enforcement or checks

## Exceptions or edge cases

- Exceptions or edge cases

Procedure / Checklist / Guide

## Goal

- Goal

## Preconditions

- Preconditions

## Steps

- Steps or checks

## Outputs

- Outputs or verification

## Recovery

- Recovery or stop conditions

Reference / Example

## What it is

- What it is

## Canonical fields

- Canonical fields or shape

## Allowed values

- Allowed values

## Known caveats

- Known caveats

FAQ

Use `##` headings for each question.

## Question

- Answer

## References

- `requires` should list snippet IDs; inline `@...` references should be root-relative (e.g., `@docs/snippets/...`).
- References prime context; the snippet body still needs to explain the concept on its own.
