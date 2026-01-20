---
id: teleclaude/snippets/authoring
type: guide
scope: project
description: How to author TeleClaude snippets and choose taxonomy-appropriate structure.
requires:
  - ../principles/priming.md
---

Purpose

- Make snippets the authoritative, reusable source for AI context selection.
- Capture intent, boundaries, and guarantees without drifting from code and docs.

Principles

- **Priming focus**: see @../principles/priming.md.
- **Truth over completeness**: reflect the real system, not idealized intent.
- **Explain the why**: capture guarantees, invariants, and boundaries that guide usage.
- **Concrete over generic**: use real component names/events where it clarifies behavior.
- **Self-contained**: a snippet should stand on its own without requiring external prose.
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

Decision

- Use when a choice between alternatives is made and needs to be remembered.
- Include: context, options considered, chosen approach, consequences or tradeoffs.
- Exclude: routine changes or implementation steps.

Incident

- Use for postmortems of real failures with enduring learning value.
- Include: impact, root cause, fix, prevention or guardrails.
- Exclude: minor bugs, transient errors, or routine outages.

Timeline

- Use for ordered milestones that explain evolution or major shifts.
- Include: date, event, outcome.
- Exclude: daily logs or running status updates.

FAQ

- Use for recurring questions that would otherwise be answered repeatedly.
- Include: question, answer.
- Exclude: one-off clarifications or internal notes.

References

- Keep `requires` and inline `@...` references relative to the snippet when possible.
- References prime context; the snippet body still needs to explain the concept on its own.
