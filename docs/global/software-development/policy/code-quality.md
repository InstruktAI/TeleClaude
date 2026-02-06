---
description: 'Architecture, typing, contracts, state management, error handling. Generic quality standards for all code.'
id: 'software-development/policy/code-quality'
scope: 'domain'
type: 'policy'
---

# Code Quality — Policy

## Rules

- Honor repository configuration and established conventions.
- Encode invariants explicitly and validate at boundaries.
- Preserve contract fidelity across all call chains.
- Keep responsibilities narrow and interfaces explicit.
- Fail fast on contract violations with clear diagnostics.
- Keep state ownership explicit and observable.
- Prefer simple, readable implementations over cleverness.
- Require tests or explicit justification for untested changes.
- Avoid hidden side effects; document mutation and I/O explicitly.
- Use types to express intent; narrow types at boundaries.

## Rationale

- Clear contracts reduce regressions and ease refactors.
- Explicit invariants make failures diagnosable and safe to recover.
- Consistent patterns allow cross-team tooling and automation.

## Scope

- Applies to all production code, scripts, and automation that can impact users or data.

## Enforcement

- Automated checks (lint, typecheck, tests) must pass before merge.
- Code review must verify contract clarity, error handling, and test coverage.

## Exceptions

- Emergency fixes may bypass normal breadth with explicit incident notes and follow-up tasks.
