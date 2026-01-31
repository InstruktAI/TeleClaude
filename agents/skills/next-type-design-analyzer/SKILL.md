---
name: next-type-design-analyzer
description: Analyze type design quality and invariants. Use when introducing new types, during PR creation with data models, or when refactoring type designs.
---

# Type Design Analyzer

## Purpose

Evaluate type designs for strong invariants, encapsulation, and practical usefulness.

## Scope

- Focus on invariants, state validity, and interface boundaries.
- Prioritize types that shape business logic or domain data.

## Inputs

- Type definitions under review
- Related types and usage sites
- Project type patterns and conventions

## Outputs

- Identified invariants
- Ratings with brief justification
- Actionable recommendations

## Procedure

- Identify explicit and implicit invariants (consistency, transitions, constraints).
- Assess encapsulation (1–10): can invariants be violated externally?
- Assess invariant expression (1–10): clarity and compile-time enforcement.
- Assess usefulness (1–10): bug prevention and alignment with requirements.
- Assess enforcement (1–10): construction and mutation safeguards.
- Report findings per type with ratings and justifications.
