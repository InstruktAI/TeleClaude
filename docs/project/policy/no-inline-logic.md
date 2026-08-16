---
description: Adopts the global no-inline-logic contract for every executable carrier in the TeleClaude repository.
---

# No Inline Logic — Policy

## Required reads

@~/.teleclaude/docs/software-development/policy/no-inline-logic.md

## Rules

- TeleClaude adopts the global no-inline-logic policy without qualification.
- Every configuration, declaration, orchestration, and convention carrier in this repository delegates executable behavior to a standalone script or typed module entrypoint.

## Rationale

Adoption is a project decision. Recording it here keeps the reusable global contract portable while making TeleClaude's mandate explicit in the scope that owns it.

## Scope

- Every TeleClaude repository file that can carry executable behavior.

## Enforcement

- Reviewers apply `software-development/policy/no-inline-logic` to every changed carrier file.

## Exceptions

- None.
